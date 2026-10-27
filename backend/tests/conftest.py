"""Fixtures compartilhadas. As de banco só são criadas quando algum teste as pede."""

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.database.engine import create_engine, create_session_factory

# psycopg assíncrono não funciona com o ProactorEventLoop (padrão no Windows).
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

BACKEND_DIR = Path(__file__).resolve().parents[1]
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://fogo:fogo-local-dev@localhost:5544/fogo_test"
)
_APP_TABLES = (
    "agent_decisions, averted_faults, anomaly_detections, ai_usage, kb_chunks, kb_documents, "
    "city_events, prediction_snapshots, prediction_models, "
    "dispatches, alerts, telemetry_readings, agent_positions, agent_status_history, agents, "
    "equipment_status_history, maintenance_orders, maintenance_plans, equipment, regions, "
    "organizations, users"
)
_REFERENCE_TYPES = (
    "'radar','camera','balanca','veiculo_fiscalizacao_autonomo','cancela','veiculo_transporte',"
    "'totem_estacionamento','patinete','moto_agente','viatura','semaforo','outro'"
)


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    return Settings(
        database_url=TEST_DATABASE_URL,
        app_env="test",
        log_level="WARNING",
        seed_demo_data=False,
        jwt_secret_key="chave-de-teste-com-mais-de-32-caracteres!!",  # type: ignore[arg-type]
        db_pool_size=5,
    )


@pytest.fixture(scope="session")
def migrated_database(test_settings: Settings) -> str:
    """Recria o schema do banco de testes e aplica TODAS as migrations (como em produção)."""
    sync_url = test_settings.database_url.replace("+psycopg", "")
    try:
        with psycopg.connect(sync_url, connect_timeout=3, autocommit=True) as conn:
            conn.execute("DROP SCHEMA public CASCADE")
            conn.execute("CREATE SCHEMA public")
            conn.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    except psycopg.OperationalError as exc:
        pytest.skip(
            f"PostgreSQL de testes indisponível ({exc}). Rode: docker compose up -d postgres"
        )
    env = {**os.environ, "DATABASE_URL": test_settings.database_url}
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env=env,
        check=True,
        capture_output=True,
    )
    return test_settings.database_url


@pytest.fixture(scope="session")
async def engine(test_settings: Settings, migrated_database: str) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(test_settings)
    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


@pytest.fixture
async def clean_database(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE {_APP_TABLES} RESTART IDENTITY CASCADE"))
        await connection.execute(
            text(f"DELETE FROM equipment_types WHERE code NOT IN ({_REFERENCE_TYPES})")  # noqa: S608
        )
