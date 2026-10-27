"""Montagem do PROMETHEUS por processo (API e scheduler): checkpointer, IA, base e agente.

O checkpointer usa um pool psycopg dedicado (autocommit, sem prepared statements), como
recomenda o ``langgraph-checkpoint-postgres``; as tabelas dele são criadas no bootstrap.
"""

import logging
import secrets
from dataclasses import dataclass

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.actions import ActionExecutor
from app.agent.chat import PrometheusChat
from app.agent.graph import PrometheusAgent
from app.agent.service import PrometheusService
from app.ai.crypto import SecretBox
from app.ai.gateway import AiGateway
from app.core.clock import Clock
from app.core.config import Settings
from app.core.permissions import Role
from app.core.security import PasswordHasher
from app.knowledge.embeddings import LocalEmbedder
from app.repositories.unit_of_work import SqlAlchemyUnitOfWork
from app.services.knowledge_service import KnowledgeService
from app.services.ports import UnitOfWork
from app.services.user_service import NewUser, UserService

logger = logging.getLogger(__name__)


def psycopg_conninfo(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


@dataclass(slots=True)
class PrometheusRuntime:
    pool: AsyncConnectionPool
    gateway: AiGateway
    knowledge: KnowledgeService
    service: PrometheusService
    agent: PrometheusAgent
    chat: PrometheusChat

    async def close(self) -> None:
        await self.pool.close()


def build_gateway(
    session_factory: async_sessionmaker[AsyncSession], clock: Clock, settings: Settings
) -> AiGateway:
    def uow_factory() -> UnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory)

    return AiGateway(
        uow_factory,
        clock,
        SecretBox(
            settings.ai_encryption_key.get_secret_value(),
            settings.jwt_secret_key.get_secret_value(),
        ),
        settings.tz,
        settings.ai_timeout_seconds,
    )


def build_knowledge(
    session_factory: async_sessionmaker[AsyncSession],
    clock: Clock,
    settings: Settings,
    gateway: AiGateway | None,
) -> KnowledgeService:
    return KnowledgeService(
        SqlAlchemyUnitOfWork(session_factory),
        clock,
        LocalEmbedder(settings.embeddings_model, settings.embeddings_cache_dir),
        gateway,
    )


async def ensure_prometheus_user(
    session_factory: async_sessionmaker[AsyncSession], clock: Clock, settings: Settings
) -> None:
    """Usuário de sistema que assina as ações automáticas (senha aleatória, nunca usada)."""
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        if await uow.users.get_by_email(settings.prometheus_email) is not None:
            return
    await UserService(SqlAlchemyUnitOfWork(session_factory), clock, PasswordHasher()).create(
        NewUser(
            email=settings.prometheus_email,
            full_name="PROMETHEUS (agente autônomo)",
            password=secrets.token_urlsafe(48),
            role=Role.OPERADOR,
        )
    )
    logger.info("Usuário de sistema do PROMETHEUS criado")


async def build_runtime(
    session_factory: async_sessionmaker[AsyncSession], clock: Clock, settings: Settings
) -> PrometheusRuntime:
    pool = AsyncConnectionPool(
        psycopg_conninfo(settings.database_url),
        min_size=1,
        max_size=4,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        # Testa a conexão antes de entregar: após um restart do banco, descarta as mortas.
        check=AsyncConnectionPool.check_connection,
    )
    await pool.open()
    checkpointer = AsyncPostgresSaver(pool)  # type: ignore[arg-type]

    def uow_factory() -> UnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory)

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        actor = await uow.users.get_by_email(settings.prometheus_email)
    if actor is None:
        await ensure_prometheus_user(session_factory, clock, settings)
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            actor = await uow.users.get_by_email(settings.prometheus_email)
    assert actor is not None  # noqa: S101  (criado logo acima)

    gateway = build_gateway(session_factory, clock, settings)
    knowledge = build_knowledge(session_factory, clock, settings, gateway)
    agent = PrometheusAgent(
        uow_factory=uow_factory,
        clock=clock,
        knowledge=knowledge,
        gateway=gateway,
        executor=ActionExecutor(uow_factory, clock, actor.id),
        checkpointer=checkpointer,
    )
    service = PrometheusService(uow_factory, clock, agent)
    chat = PrometheusChat(uow_factory, gateway, knowledge)
    return PrometheusRuntime(pool, gateway, knowledge, service, agent, chat)


async def setup_checkpointer(settings: Settings) -> None:
    """Cria/migra as tabelas do checkpointer do LangGraph (idempotente; bootstrap)."""
    async with AsyncPostgresSaver.from_conn_string(
        psycopg_conninfo(settings.database_url)
    ) as saver:
        await saver.setup()
