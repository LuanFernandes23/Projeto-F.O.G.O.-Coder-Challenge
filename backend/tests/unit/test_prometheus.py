"""PROMETHEUS: política de autonomia, situações, RAG puro, cifra da chave e o grafo com HITL."""

import uuid
from datetime import UTC, datetime
from types import TracebackType
from typing import Any, Self
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.agent.actions import Validation
from app.agent.graph import PrometheusAgent, situation_to_dict
from app.agent.situations import build_situations, precursor_confidence
from app.ai.crypto import SecretBox
from app.ai.gateway import AiGateway
from app.core.clock import ManualClock
from app.core.exceptions import IntegrationError
from app.domain.ai_settings import (
    AiProvider,
    AiSettings,
    EmbeddingsProvider,
    default_settings,
    mask_key,
)
from app.domain.knowledge.retrieval import (
    Bm25Index,
    evidence_from_similarity,
    parse_markdown,
    rrf,
    split_markdown,
)
from app.domain.prometheus.entities import (
    DEFAULT_POLICIES,
    ActionType,
    AutonomyPolicy,
    Decision,
    DecisionMode,
    DecisionStatus,
    PrometheusMode,
    RiskClass,
    Situation,
    SituationKind,
    autonomy_decision,
)
from app.services.knowledge_service import SearchHit

POLICIES = {p.action_type: p for p in DEFAULT_POLICIES}


# ---- política de autonomia ---------------------------------------------------------------


def _decide(**overrides: Any) -> Any:
    args: dict[str, Any] = {
        "action": ActionType.ABRIR_OS_PREVENTIVA,
        "confidence": 0.8,
        "evidence": 0.9,
        "allowed_risk": RiskClass.MEDIO,
        "policy": POLICIES[ActionType.ABRIR_OS_PREVENTIVA],
        "mode": PrometheusMode.AUTONOMO,
        "auto_executed_last_hour": 0,
        "plan_valid": True,
    }
    return autonomy_decision(**{**args, **overrides})


def test_acts_alone_only_when_every_condition_holds() -> None:
    assert _decide().auto
    assert _decide().score == pytest.approx(0.72)


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"mode": PrometheusMode.SUGESTAO}, "Modo de sugestão"),
        ({"plan_valid": False}, "validação"),
        ({"confidence": 0.3}, "abaixo do limiar"),
        ({"auto_executed_last_hour": 6}, "Teto"),
        ({"allowed_risk": RiskClass.BAIXO, "action": ActionType.DESPACHAR_INSPECAO}, "risco até"),
        (
            {
                "action": ActionType.REFORCAR_REGIAO,
                "policy": AutonomyPolicy(ActionType.REFORCAR_REGIAO, 0.0, True, 10),
                "allowed_risk": RiskClass.ALTO,
                "confidence": 1.0,
                "evidence": 1.0,
            },
            "risco alto",
        ),
    ],
)
def test_any_failed_condition_asks_a_human_with_a_reason(
    overrides: dict[str, Any], reason: str
) -> None:
    result = _decide(**overrides)
    assert not result.auto
    assert any(reason in r for r in result.reasons)


# ---- situações ------------------------------------------------------------------------------


def test_precursor_confidence_learns_from_outcomes() -> None:
    assert precursor_confidence({}) == pytest.approx(0.75)  # prior Beta(3, 1)
    good = precursor_confidence({"detections_confirmed": 8, "detections_averted": 4})
    bad = precursor_confidence({"detections_confirmed": 1, "false_alarms": 12})
    assert good > 0.9 > 0.3 > bad


def test_situations_from_snapshots_merge_moves_per_region() -> None:
    region = uuid.uuid4()
    anomalies = {
        "quality": {},
        "devices": [
            {
                "equipment_id": str(uuid.uuid4()),
                "serial_number": "SEM-1",
                "type_code": "semaforo",
                "region": "centro",
                "neighborhood": "Centro",
                "score": 0.8,
                "signals": [{"label": "Temperatura", "value": 41, "baseline": 30, "z": 9}],
            }
        ],
        "regional": [],
    }
    city = {
        "equipment_risk": [],
        "reinforcement": [
            {
                "starts_at": "2026-10-27T16:00:00",
                "ends_at": "2026-10-27T20:00:00",
                "regions": [
                    {"region": "norte", "recommended": 9, "staffed": 4, "gap": 5, "reason": "x"}
                ],
                "moves": [
                    {"from": "centro", "to": "norte", "agents": 3},
                    {"from": "oeste", "to": "norte", "agents": 2},
                ],
            }
        ],
    }
    names = {"centro": "Centro", "norte": "Zona Norte", "oeste": "Zona Oeste"}
    situations = build_situations(city, anomalies, {"centro": region, "norte": region}, names)
    kinds = [s.kind for s in situations]
    assert kinds == [SituationKind.PRECURSOR_FALHA, SituationKind.DEFICIT_EFETIVO]
    deficit = situations[1]
    assert deficit.facts["agents"] == 5
    assert deficit.facts["from_region"] == "centro"


# ---- RAG puro e cifra -----------------------------------------------------------------------


def test_markdown_front_matter_and_heading_chunks() -> None:
    doc = parse_markdown(
        "pop-x",
        "---\ntitulo: POP X\ntipo: procedimento\nacoes_permitidas: [abrir_os_preventiva]\n---\n"
        "# POP X\n\n## Quando aplicar\nTexto A.\n\n## Ação\nTexto B.",
    )
    assert (doc.title, doc.doc_type) == ("POP X", "procedimento")
    assert doc.metadata["acoes_permitidas"] == ["abrir_os_preventiva"]
    chunks = split_markdown(doc.title, doc.body)
    assert [c.heading for c in chunks] == ["POP X › Quando aplicar", "POP X › Ação"]

    # O aviso abaixo do título não vira um trecho próprio (tomaria vaga das seções na busca).
    chunks = split_markdown("POP X", "# POP X\n\n> Fictício.\n\n## Quando aplicar\nTexto A.")
    assert [(c.heading, c.content) for c in chunks] == [
        ("POP X › Quando aplicar", "> Fictício.\n\n\nTexto A.")
    ]


def test_bm25_and_rrf_rank_the_relevant_passage_first() -> None:
    index = Bm25Index.build(
        [(1, ["semafor", "falh", "temperatur"]), (2, ["patinet", "bater"]), (3, ["semafor"])]
    )
    assert [i for i, _ in index.search(["semafor", "temperatur"], 3)] == [1, 3]
    fused = rrf({"bm25": [1, 3], "vetor": [3, 1, 2]})
    assert {fused[0][0], fused[1][0]} == {1, 3}
    assert fused[-1][0] == 2
    assert evidence_from_similarity(0.1) == 0.0
    assert evidence_from_similarity(0.6) == 1.0


def test_api_key_is_encrypted_and_only_last_four_leave_the_server() -> None:
    box = SecretBox("", "segredo-jwt-de-teste")
    token = box.encrypt("sk-proj-abcdefgh1234")
    assert b"abcdefgh" not in token
    assert box.decrypt(token) == "sk-proj-abcdefgh1234"
    assert mask_key("sk-proj-abcdefgh1234") == "1234"
    settings = default_settings()
    assert not settings.usable  # IA desligada por padrão: o sistema roda sem chave
    settings.enabled, settings.provider = True, AiProvider.OPENAI_COMPATIBLE
    assert settings.usable  # servidor local compatível dispensa chave


class QuotaError(Exception):
    status_code = 429


class FakeEmbeddings:
    def __init__(self, fail: bool) -> None:
        self.fail = fail

    async def aembed_query(self, text: str) -> list[float]:
        return (await self.aembed_documents([text]))[0]

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        if self.fail:
            raise QuotaError("quota exceeded")
        return [[0.1, 0.2] for _ in texts]


class FakeAiRepo:
    def __init__(self, settings: AiSettings) -> None:
        self.settings = settings
        self.usage: list[dict[str, Any]] = []

    async def get_settings(self) -> AiSettings:
        return self.settings

    async def add_usage(self, **row: Any) -> None:
        self.usage.append(row)


class AiUow:
    def __init__(self, repo: FakeAiRepo) -> None:
        self.ai = repo

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def commit(self) -> None:
        return None


def _embedding_gateway(monkeypatch: pytest.MonkeyPatch, *, fail: bool) -> tuple[Any, FakeAiRepo]:
    box = SecretBox("", "segredo-jwt-de-teste")
    settings = default_settings()
    settings.enabled = True
    settings.api_key_encrypted = box.encrypt("sk-proj-abcdefgh1234")
    settings.embeddings_provider = EmbeddingsProvider.OPENAI
    repo = FakeAiRepo(settings)
    monkeypatch.setattr(
        "app.ai.gateway.build_embeddings",
        lambda provider, key: (FakeEmbeddings(fail), "text-embedding-3-small"),
    )
    tz = ZoneInfo("America/Sao_Paulo")
    gateway = AiGateway(
        lambda: AiUow(repo),  # type: ignore[arg-type, return-value]
        ManualClock(datetime(2026, 10, 27, 15, tzinfo=UTC), tz),
        box,
        tz,
        5.0,
    )
    return gateway, repo


async def test_provider_embeddings_are_recorded_as_ai_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway, repo = _embedding_gateway(monkeypatch, fail=False)
    vectors, model = await gateway.embed_documents(["a" * 40, "b" * 40])
    assert (len(vectors), model) == (2, "text-embedding-3-small")
    [row] = repo.usage
    assert (row["feature"], row["provider"], row["ok"]) == ("embeddings_base", "openai", True)
    assert row["input_tokens"] == 21  # estimativa: ~4 caracteres por token


async def test_query_embedding_failure_degrades_to_local_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway, repo = _embedding_gateway(monkeypatch, fail=True)
    assert await gateway.embed_query("semáforo apagado") is None  # a busca segue sem o provedor
    assert [(r["feature"], r["ok"]) for r in repo.usage] == [("embeddings_busca", False)]
    with pytest.raises(IntegrationError):  # indexar sem o vetor do provedor seria silencioso
        await gateway.embed_documents(["texto"])


# ---- grafo com humano no circuito --------------------------------------------------------------


class FakePrometheusRepo:
    def __init__(self) -> None:
        self.decisions: dict[UUID, Decision] = {}
        self.mode_value = PrometheusMode.AUTONOMO

    async def mode(self) -> tuple[PrometheusMode, int]:
        return self.mode_value, 30

    async def policies(self) -> list[AutonomyPolicy]:
        return list(DEFAULT_POLICIES)

    async def auto_executed_since(self, action: ActionType, since: datetime) -> int:
        return 0

    async def add_decision(self, decision: Decision) -> None:
        self.decisions[decision.id] = decision

    async def update_decision(self, decision: Decision) -> None:
        self.decisions[decision.id] = decision

    async def get_decision(self, decision_id: UUID, *, for_update: bool = False) -> Decision | None:
        return self.decisions.get(decision_id)


class FakeEvents:
    async def publish(self, event: Any) -> None:
        return None


class FakeUow:
    def __init__(self, repo: FakePrometheusRepo) -> None:
        self.prometheus = repo
        self.events = FakeEvents()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    async def commit(self) -> None:
        return None


class FakeKnowledge:
    def __init__(self, actions: list[str], autonomy: str, similarity: float = 0.6) -> None:
        self._chunk = {
            "title": "POP de teste",
            "slug": "pop-teste",
            "document_id": str(uuid.uuid4()),
            "heading": "POP › Ação",
            "content": "Abrir OS preventiva imediata.",
            "doc_type": "procedimento",
            "metadata": {
                "acoes_permitidas": actions,
                "acao_padrao": actions[0],
                "autonomia_max": autonomy,
                "situacoes": ["precursor_falha"],
            },
        }
        self._similarity = similarity

    async def search(self, query: str, **_: Any) -> list[SearchHit]:
        return [SearchHit(self._chunk, 0.03, {"bm25": 1, "vetor_local": 1}, self._similarity)]


class NoAi:
    async def structured(self, *_: Any, **__: Any) -> None:
        return None  # IA desligada → planejador determinístico


class FakeExecutor:
    def __init__(self) -> None:
        self.executed: list[tuple[ActionType, dict[str, Any]]] = []

    async def validate(self, action: ActionType, params: dict[str, Any]) -> Validation:
        return Validation(True, params, "ok")

    async def execute(self, action: ActionType, params: dict[str, Any]) -> dict[str, Any]:
        self.executed.append((action, params))
        return {"ok": True, "message": "feito"}


def _agent(
    knowledge: FakeKnowledge,
    repo: FakePrometheusRepo,
    executor: FakeExecutor,
    gateway: Any = None,
) -> PrometheusAgent:
    return PrometheusAgent(
        uow_factory=lambda: FakeUow(repo),  # type: ignore[arg-type, return-value]
        clock=ManualClock(datetime(2026, 10, 27, 15, tzinfo=UTC), ZoneInfo("America/Sao_Paulo")),
        knowledge=knowledge,  # type: ignore[arg-type]
        gateway=gateway or NoAi(),
        executor=executor,  # type: ignore[arg-type]
        checkpointer=InMemorySaver(),
    )


def _situation(confidence: float) -> dict[str, Any]:
    situation = Situation(
        key="precursor:x",
        kind=SituationKind.PRECURSOR_FALHA,
        title="Sinais de falha iminente: semaforo SEM-1",
        summary="Temperatura subindo e sinal caindo.",
        confidence=confidence,
        equipment_id=uuid.uuid4(),
        type_code="semaforo",
    )
    return {**situation_to_dict(situation), "thread_id": "t"}


async def test_high_confidence_low_risk_action_runs_without_asking() -> None:
    repo, executor = FakePrometheusRepo(), FakeExecutor()
    agent = _agent(FakeKnowledge(["abrir_os_preventiva"], "medio"), repo, executor)
    state = await agent.graph.ainvoke(
        {"situation": _situation(0.9)}, {"configurable": {"thread_id": "auto"}}
    )
    assert "__interrupt__" not in state
    assert executor.executed[0][0] is ActionType.ABRIR_OS_PREVENTIVA
    [decision] = repo.decisions.values()
    assert (decision.status, decision.mode) == (DecisionStatus.EXECUTADA, DecisionMode.AUTOMATICA)
    assert decision.citations[0]["title"] == "POP de teste"


async def test_low_confidence_pauses_for_a_human_and_resumes_on_approval() -> None:
    repo, executor = FakePrometheusRepo(), FakeExecutor()
    agent = _agent(FakeKnowledge(["abrir_os_preventiva"], "medio"), repo, executor)
    config = {"configurable": {"thread_id": "hitl"}}
    state = await agent.graph.ainvoke({"situation": _situation(0.3)}, config)
    assert "__interrupt__" in state
    assert not executor.executed
    [pending] = repo.decisions.values()
    assert pending.status is DecisionStatus.PENDENTE
    assert pending.expires_at is not None
    assert pending.expires_at > pending.created_at

    approver = uuid.uuid4()
    await agent.graph.ainvoke(
        Command(resume={"approved": True, "user_id": str(approver), "note": None}), config
    )
    decision = repo.decisions[pending.id]
    assert (decision.status, decision.mode, decision.decided_by) == (
        DecisionStatus.EXECUTADA,
        DecisionMode.HUMANA,
        approver,
    )
    assert len(executor.executed) == 1


async def test_rejection_records_the_reason_and_executes_nothing() -> None:
    repo, executor = FakePrometheusRepo(), FakeExecutor()
    agent = _agent(FakeKnowledge(["despachar_inspecao"], "baixo"), repo, executor)
    config = {"configurable": {"thread_id": "reject"}}
    await agent.graph.ainvoke({"situation": _situation(0.95)}, config)
    [pending] = repo.decisions.values()
    assert any("risco até" in r for r in pending.score["reasons"])
    await agent.graph.ainvoke(
        Command(resume={"approved": False, "user_id": str(uuid.uuid4()), "note": "Sem efetivo"}),
        config,
    )
    assert repo.decisions[pending.id].status is DecisionStatus.REJEITADA
    assert repo.decisions[pending.id].error == "Sem efetivo"
    assert not executor.executed


async def test_no_authorizing_procedure_means_no_action() -> None:
    repo, executor = FakePrometheusRepo(), FakeExecutor()
    agent = _agent(FakeKnowledge(["abrir_os_preventiva"], "medio", similarity=0.1), repo, executor)
    await agent.graph.ainvoke({"situation": _situation(0.99)}, {"configurable": {"thread_id": "n"}})
    [decision] = repo.decisions.values()
    assert decision.status is DecisionStatus.FALHOU
    assert not executor.executed


class TwoProcedures(FakeKnowledge):
    """O trecho mais bem ranqueado é de outro tipo de equipamento (não autoriza a situação)."""

    def __init__(self) -> None:
        super().__init__(["abrir_os_preventiva"], "medio")
        other = dict(self._chunk, title="POP de patinetes", slug="pop-patinetes")
        other["metadata"] = {**self._chunk["metadata"], "tipos_equipamento": ["patinete"]}
        right = dict(self._chunk, title="POP de semáforos", slug="pop-semaforos")
        right["metadata"] = {**self._chunk["metadata"], "tipos_equipamento": ["semaforo"]}
        self._chunks = [other, right]

    async def search(self, query: str, **_: Any) -> list[SearchHit]:
        return [SearchHit(c, 0.03, {"bm25": 1}, self._similarity) for c in self._chunks]


async def test_rationale_cites_the_procedure_that_authorizes_the_equipment_type() -> None:
    repo, executor = FakePrometheusRepo(), FakeExecutor()
    agent = _agent(TwoProcedures(), repo, executor)
    await agent.graph.ainvoke({"situation": _situation(0.9)}, {"configurable": {"thread_id": "c"}})
    [decision] = repo.decisions.values()
    assert "POP de semáforos" in decision.rationale
    assert "patinetes" not in decision.rationale
    # A citação que vale para a situação vem primeiro; a outra fica registrada, marcada.
    assert [(c["title"], c["applies"]) for c in decision.citations] == [
        ("POP de semáforos", True),
        ("POP de patinetes", False),
    ]


class RecordingAi:
    def __init__(self) -> None:
        self.prompt = ""

    async def structured(
        self, feature: str, schema: Any, messages: list[Any], **_: Any
    ) -> tuple[Any, int]:
        self.prompt = str(messages[-1].content)
        return schema(action_type="abrir_os_preventiva", rationale="Conforme o trecho 2."), 50


async def test_llm_only_sees_passages_that_apply_to_the_situation() -> None:
    repo, executor, ai = FakePrometheusRepo(), FakeExecutor(), RecordingAi()
    agent = _agent(TwoProcedures(), repo, executor, ai)
    await agent.graph.ainvoke({"situation": _situation(0.9)}, {"configurable": {"thread_id": "l"}})
    assert "POP de semáforos" in ai.prompt
    assert "POP de patinetes" not in ai.prompt
    [decision] = repo.decisions.values()
    assert (decision.planner.value, decision.tokens) == ("llm", 50)
