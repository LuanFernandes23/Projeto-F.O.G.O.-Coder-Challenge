"""Criação do engine assíncrono (com pool explícito) e da fábrica de sessões.

Nada aqui roda no import: o engine é criado no lifespan da aplicação (ou do job).
"""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_seconds,
        pool_recycle=settings.db_pool_recycle_seconds,
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": settings.db_connect_timeout_seconds,
            # Timeout de consulta no servidor: nenhuma query trava um worker indefinidamente.
            "options": f"-c statement_timeout={settings.db_statement_timeout_ms}",
            "application_name": "fogo-api",
        },
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
