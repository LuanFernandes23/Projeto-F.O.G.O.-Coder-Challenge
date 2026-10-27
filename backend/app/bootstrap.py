"""Inicialização pós-migração: primeiro administrador e (opcional) dados de demonstração.

Uso: ``python -m app.bootstrap`` (executado pelo serviço ``migrate`` do compose).
"""

import asyncio
import logging
import sys

from app.agent.runtime import (
    build_gateway,
    build_knowledge,
    ensure_prometheus_user,
    setup_checkpointer,
)
from app.core.clock import SystemClock
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.security import PasswordHasher
from app.database.engine import create_engine, create_session_factory
from app.repositories.unit_of_work import SqlAlchemyUnitOfWork
from app.seed.demo_seed import DemoSeeder
from app.services.user_service import UserService

logger = logging.getLogger("app.bootstrap")


async def run(settings: Settings) -> None:
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    try:
        users = UserService(
            SqlAlchemyUnitOfWork(session_factory), SystemClock(settings.tz), PasswordHasher()
        )
        created = await users.ensure_first_admin(
            settings.first_admin_email,
            settings.first_admin_name,
            settings.first_admin_password.get_secret_value(),
        )
        logger.info("Primeiro administrador", extra={"admin_created": created})
        if settings.seed_demo_data:
            await DemoSeeder(session_factory, settings).run_if_empty()
        # Parte 3: usuário de sistema do PROMETHEUS, checkpointer do LangGraph e base de
        # conhecimento (idempotentes: só reindexam documentos alterados).
        clock = SystemClock(settings.tz)
        await ensure_prometheus_user(session_factory, clock, settings)
        await setup_checkpointer(settings)
        gateway = build_gateway(session_factory, clock, settings)
        knowledge = build_knowledge(session_factory, clock, settings, gateway)
        result = await knowledge.ingest_directory(settings.knowledge_dir)
        logger.info("Base de conhecimento", extra=result)
    finally:
        await engine.dispose()


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    if sys.platform == "win32":  # psycopg assíncrono não suporta o ProactorEventLoop
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run(settings))


if __name__ == "__main__":
    main()
