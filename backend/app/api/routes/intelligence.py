"""Rotas da Parte 3: IA do usuário (BYOK), base de conhecimento e PROMETHEUS."""

import json
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status
from fastapi.responses import StreamingResponse

from app.api.dependencies.auth import CurrentUser, Requires
from app.api.dependencies.services import AiSettingsServiceDep, PrometheusRuntimeDep
from app.api.routes.common import AUTH_PROBLEMS, problems
from app.core.permissions import Permission
from app.domain.prometheus.entities import AutonomyPolicy, DecisionStatus
from app.schemas.intelligence import (
    AiCandidateInput,
    AiSaveOutput,
    AiSettingsInput,
    AiSettingsOutput,
    AiTestOutput,
    AiUsageOutput,
    ChatInput,
    DecisionAnswerInput,
    DecisionOutput,
    KnowledgeDocumentDetail,
    KnowledgeDocumentInput,
    KnowledgeDocumentOutput,
    KnowledgeHitOutput,
    KnowledgeSearchInput,
    PolicyOutput,
    PrometheusSettingsInput,
    PrometheusSettingsOutput,
    PrometheusStatsOutput,
)
from app.services.ai_settings_service import AiSettingsChanges

# ---- IA do usuário -----------------------------------------------------------------------

ai_router = APIRouter(
    prefix="/ai",
    tags=["Inteligência artificial"],
    dependencies=[Requires(Permission.AI_CONFIGURE)],
    responses=AUTH_PROBLEMS,
)


@ai_router.get(
    "/settings", response_model=AiSettingsOutput, summary="Configuração (chave mascarada)"
)
async def get_ai_settings(service: AiSettingsServiceDep) -> AiSettingsOutput:
    return AiSettingsOutput.from_domain(await service.get())


@ai_router.put(
    "/settings",
    response_model=AiSaveOutput,
    summary="Salvar provedor, modelo, chave e limites (a chave é só de escrita)",
    responses=problems(422),
)
async def save_ai_settings(
    payload: AiSettingsInput,
    service: AiSettingsServiceDep,
    runtime: PrometheusRuntimeDep,
    user: CurrentUser,
) -> AiSaveOutput:
    saved, embeddings_changed = await service.update(
        AiSettingsChanges(
            enabled=payload.enabled,
            provider=payload.provider,
            model=payload.model,
            base_url=payload.base_url,
            api_key=payload.api_key.get_secret_value() if payload.api_key else None,
            clear_key=payload.clear_key,
            embeddings_provider=payload.embeddings_provider,
            daily_call_limit=payload.daily_call_limit,
            daily_token_limit=payload.daily_token_limit,
        ),
        user.id,
    )
    reindexed = await runtime.knowledge.reindex_provider() if embeddings_changed else None
    return AiSaveOutput(settings=AiSettingsOutput.from_domain(saved), reindexed_chunks=reindexed)


@ai_router.post(
    "/settings/test",
    response_model=AiTestOutput,
    summary="Testar a conexão antes de salvar (chamada mínima, ~20 tokens)",
)
async def test_ai_settings(
    payload: AiCandidateInput, service: AiSettingsServiceDep
) -> AiTestOutput:
    result = await service.test(
        payload.provider,
        payload.model,
        payload.base_url,
        payload.api_key.get_secret_value() if payload.api_key else None,
    )
    return AiTestOutput(
        ok=result.ok,
        latency_ms=result.latency_ms,
        reply=result.reply,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        error=result.error,
    )


@ai_router.post(
    "/models",
    response_model=list[str],
    summary="Listar os modelos disponíveis para a chave (sem custo)",
    responses=problems(422, 502),
)
async def list_ai_models(payload: AiCandidateInput, service: AiSettingsServiceDep) -> list[str]:
    return await service.models(
        payload.provider,
        payload.base_url,
        payload.api_key.get_secret_value() if payload.api_key else None,
    )


@ai_router.get("/usage", response_model=list[AiUsageOutput], summary="Consumo por dia e uso")
async def ai_usage(
    service: AiSettingsServiceDep, days: Annotated[int, Query(ge=1, le=90)] = 14
) -> list[AiUsageOutput]:
    return [AiUsageOutput(**row) for row in await service.usage(days)]


# ---- Base de conhecimento ----------------------------------------------------------------

knowledge_router = APIRouter(
    prefix="/knowledge",
    tags=["Base de conhecimento"],
    dependencies=[Requires(Permission.OPERATIONS_READ)],
    responses=AUTH_PROBLEMS,
)


@knowledge_router.get(
    "/documents", response_model=list[KnowledgeDocumentOutput], summary="Documentos da base"
)
async def list_documents(runtime: PrometheusRuntimeDep) -> list[KnowledgeDocumentOutput]:
    return [KnowledgeDocumentOutput(**d) for d in await runtime.knowledge.list_documents()]


@knowledge_router.get(
    "/documents/{document_id}",
    response_model=KnowledgeDocumentDetail,
    summary="Documento com seus trechos indexados",
    responses=problems(404),
)
async def get_document(document_id: UUID, runtime: PrometheusRuntimeDep) -> KnowledgeDocumentDetail:
    return KnowledgeDocumentDetail(**await runtime.knowledge.get_document(document_id))


@knowledge_router.post(
    "/documents",
    response_model=KnowledgeDocumentDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Criar ou atualizar documento (reindexa os trechos)",
    dependencies=[Requires(Permission.KNOWLEDGE_MANAGE)],
    responses=problems(422),
)
async def save_document(
    payload: KnowledgeDocumentInput, runtime: PrometheusRuntimeDep, user: CurrentUser
) -> KnowledgeDocumentDetail:
    document_id = await runtime.knowledge.save_document(
        slug=payload.slug,
        title=payload.title,
        doc_type=payload.doc_type,
        metadata=payload.metadata(),
        body=payload.body,
        actor_id=user.id,
    )
    return KnowledgeDocumentDetail(**await runtime.knowledge.get_document(document_id))


@knowledge_router.delete(
    "/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Excluir documento",
    dependencies=[Requires(Permission.KNOWLEDGE_MANAGE)],
    responses=problems(404),
)
async def delete_document(document_id: UUID, runtime: PrometheusRuntimeDep) -> Response:
    await runtime.knowledge.delete_document(document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@knowledge_router.post(
    "/search",
    response_model=list[KnowledgeHitOutput],
    summary="Busca híbrida (BM25 + vetores, fusão RRF), com a posição em cada busca",
)
async def search(
    payload: KnowledgeSearchInput, runtime: PrometheusRuntimeDep
) -> list[KnowledgeHitOutput]:
    hits = await runtime.knowledge.search(
        payload.query,
        limit=payload.limit,
        situation=payload.situation.value if payload.situation else None,
    )
    return [KnowledgeHitOutput(**h.as_dict()) for h in hits]


# ---- PROMETHEUS ----------------------------------------------------------------------------

prometheus_router = APIRouter(
    prefix="/prometheus",
    tags=["PROMETHEUS"],
    dependencies=[Requires(Permission.OPERATIONS_READ)],
    responses=AUTH_PROBLEMS,
)


@prometheus_router.get(
    "/decisions", response_model=list[DecisionOutput], summary="Decisões (trilha de auditoria)"
)
async def list_decisions(
    runtime: PrometheusRuntimeDep,
    status_filter: Annotated[list[DecisionStatus] | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[DecisionOutput]:
    decisions = await runtime.service.decisions(status_filter, limit)
    return [DecisionOutput.from_domain(d) for d in decisions]


@prometheus_router.get(
    "/decisions/{decision_id}",
    response_model=DecisionOutput,
    summary="Detalhe de uma decisão",
    responses=problems(404),
)
async def get_decision(decision_id: UUID, runtime: PrometheusRuntimeDep) -> DecisionOutput:
    return DecisionOutput.from_domain(await runtime.service.get(decision_id))


@prometheus_router.post(
    "/decisions/{decision_id}/approve",
    response_model=DecisionOutput,
    summary="Aprovar a ação (retoma o grafo pausado)",
    dependencies=[Requires(Permission.PROMETHEUS_APPROVE)],
    responses=problems(404, 409, 422),
)
async def approve(
    decision_id: UUID,
    payload: DecisionAnswerInput,
    runtime: PrometheusRuntimeDep,
    user: CurrentUser,
) -> DecisionOutput:
    decision = await runtime.service.decide(
        decision_id, approved=True, user_id=user.id, note=payload.note
    )
    return DecisionOutput.from_domain(decision)


@prometheus_router.post(
    "/decisions/{decision_id}/reject",
    response_model=DecisionOutput,
    summary="Rejeitar a ação (retoma o grafo pausado, sem executar)",
    dependencies=[Requires(Permission.PROMETHEUS_APPROVE)],
    responses=problems(404, 409, 422),
)
async def reject(
    decision_id: UUID,
    payload: DecisionAnswerInput,
    runtime: PrometheusRuntimeDep,
    user: CurrentUser,
) -> DecisionOutput:
    decision = await runtime.service.decide(
        decision_id, approved=False, user_id=user.id, note=payload.note
    )
    return DecisionOutput.from_domain(decision)


@prometheus_router.get("/stats", response_model=PrometheusStatsOutput, summary="Resumo de atuação")
async def stats(
    runtime: PrometheusRuntimeDep, hours: Annotated[int, Query(ge=1, le=24 * 30)] = 24
) -> PrometheusStatsOutput:
    return PrometheusStatsOutput(**await runtime.service.stats(hours))


@prometheus_router.get(
    "/settings", response_model=PrometheusSettingsOutput, summary="Modo e políticas de autonomia"
)
async def get_settings(runtime: PrometheusRuntimeDep) -> PrometheusSettingsOutput:
    mode, ttl, policies = await runtime.service.settings()
    return PrometheusSettingsOutput(
        mode=mode,
        approval_ttl_minutes=ttl,
        policies=[PolicyOutput.from_domain(p) for p in policies],
    )


@prometheus_router.put(
    "/settings",
    response_model=PrometheusSettingsOutput,
    summary="Alterar modo e políticas de autonomia",
    dependencies=[Requires(Permission.PROMETHEUS_MANAGE)],
    responses=problems(422),
)
async def update_settings(
    payload: PrometheusSettingsInput, runtime: PrometheusRuntimeDep, user: CurrentUser
) -> PrometheusSettingsOutput:
    await runtime.service.update_settings(
        payload.mode,
        payload.approval_ttl_minutes,
        [
            AutonomyPolicy(p.action_type, p.threshold, p.enabled, p.max_per_hour)
            for p in payload.policies
        ],
        user.id,
    )
    return await get_settings(runtime)


@prometheus_router.post(
    "/cycle",
    summary="Rodar um ciclo de percepção e decisão agora",
    dependencies=[Requires(Permission.PROMETHEUS_MANAGE)],
)
async def run_cycle(runtime: PrometheusRuntimeDep) -> dict[str, object]:
    return await runtime.service.cycle()


@prometheus_router.post(
    "/chat",
    summary="Pergunte ao PROMETHEUS (SSE: token, tool, done, error)",
    response_class=StreamingResponse,
)
async def chat(
    payload: ChatInput, runtime: PrometheusRuntimeDep, user: CurrentUser
) -> StreamingResponse:
    async def events() -> AsyncIterator[str]:
        history = [m.model_dump() for m in payload.messages]
        async for event in runtime.chat.stream(history, str(user.id)):
            yield f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
