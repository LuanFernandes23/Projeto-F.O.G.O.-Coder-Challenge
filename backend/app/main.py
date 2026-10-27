"""Fábrica da aplicação FastAPI (``uvicorn app.main:create_app --factory``).

Nenhum recurso é criado no import: engine, pool e cliente HTTP nascem no lifespan.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.dependencies.container import AppContainer
from app.api.error_handlers import register_error_handlers
from app.api.middleware import RequestContextMiddleware
from app.api.routes import (
    addresses,
    agents,
    alerts,
    auth,
    dispatches,
    equipment,
    health,
    intelligence,
    maintenance,
    operations,
    predictions,
    reference,
    stream,
    telemetry,
    users,
)
from app.core.cache import TtlCache
from app.core.clock import Clock, SystemClock
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.security import PasswordHasher, TokenService
from app.database.engine import create_engine, create_session_factory
from app.realtime.broker import EventBroker

logger = logging.getLogger(__name__)

API_DESCRIPTION = """
**F.O.G.O. — Ferramenta Onisciente de Gestão e Operações**

Parte 1 — *Inventário Inteligente da Cidade*: catálogo de equipamentos IoT de trânsito e
segurança e dos agentes de campo, com localização georreferenciada (PostGIS), máquina de
estados auditável, manutenção inteligente e autopreenchimento de endereço por CEP.

Autentique-se em **Authorize** com um usuário do seed (ex.: `admin@fogo.dev`).
Erros seguem o padrão `application/problem+json` (RFC 9457).
"""

OPENAPI_TAGS = [
    {"name": "Autenticação", "description": "Login JWT e dados do usuário logado."},
    {"name": "Central de Operações", "description": "KPIs, mapa, saúde das regiões, análises."},
    {"name": "Alertas", "description": "Alertas com criticidade e SLA."},
    {"name": "PROMETHEUS", "description": "Agente LangGraph: decisões, aprovação humana e chat."},
    {"name": "Base de conhecimento", "description": "RAG híbrido (BM25 + vetores + RRF)."},
    {"name": "Inteligência artificial", "description": "Chave do modelo de IA do usuário (BYOK)."},
    {
        "name": "Cidade Preditiva",
        "description": "Previsões explicáveis, backtest, anomalias e falhas evitadas.",
    },
    {"name": "Despachos", "description": "Despacho inteligente de agentes."},
    {"name": "Tempo real", "description": "Fluxo de eventos (Server-Sent Events)."},
    {"name": "Telemetria IoT", "description": "Ingestão do gateway IoT (X-Gateway-Key)."},
    {"name": "Equipamentos", "description": "Inventário, filtros geográficos e situação."},
    {"name": "Manutenção", "description": "Plano periódico e ordens de manutenção."},
    {"name": "Agentes", "description": "Agentes de trânsito, guardas e policiais."},
    {"name": "Tipos de equipamento", "description": "Tipos e JSON Schema das características."},
    {"name": "Órgãos", "description": "Órgãos responsáveis."},
    {"name": "Regiões", "description": "Regiões da cidade (polígonos)."},
    {"name": "Catálogos", "description": "Situações e transições para o front-end."},
    {"name": "Endereços", "description": "Consulta de CEP com fallback."},
    {"name": "Usuários", "description": "Gestão de usuários (admin)."},
    {"name": "Saúde", "description": "Health checks."},
]


def build_container(settings: Settings, clock: Clock | None = None) -> AppContainer:
    engine = create_engine(settings)
    return AppContainer(
        settings=settings,
        engine=engine,
        session_factory=create_session_factory(engine),
        http_client=httpx.AsyncClient(
            timeout=httpx.Timeout(settings.http_timeout_seconds),
            headers={"User-Agent": "fogo-api/0.1"},
            follow_redirects=False,
        ),
        clock=clock or SystemClock(settings.tz),
        password_hasher=PasswordHasher(),
        token_service=TokenService(
            settings.jwt_secret_key.get_secret_value(),
            settings.jwt_algorithm,
            settings.jwt_access_token_expire_minutes,
        ),
        cep_cache=TtlCache(settings.cep_cache_ttl_seconds, settings.cep_cache_max_entries),
        event_broker=EventBroker(
            settings.database_url.replace("+psycopg", ""), settings.sse_queue_size
        ),
    )


def create_app(settings: Settings | None = None, container: AppContainer | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        resources = container or build_container(settings)
        app.state.container = resources
        resources.event_broker.start()
        logger.info("Aplicação iniciada", extra={"env": settings.app_env})
        try:
            yield
        finally:
            await resources.event_broker.stop()
            if resources.prometheus is not None:
                await resources.prometheus.close()
            await resources.http_client.aclose()
            await resources.engine.dispose()
            logger.info("Aplicação finalizada")

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description=API_DESCRIPTION,
        openapi_tags=OPENAPI_TAGS,
        lifespan=lifespan,
        swagger_ui_parameters={"persistAuthorization": True},
    )
    app.add_middleware(RequestContextMiddleware)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Request-ID"],
        )
    register_error_handlers(app)

    api = APIRouter(prefix="/api/v1")
    modules = (
        auth,
        operations,
        alerts,
        dispatches,
        stream,
        equipment,
        maintenance,
        agents,
        reference,
        addresses,
        users,
        telemetry,
        predictions,
    )
    for module in modules:
        api.include_router(module.router)
    for router in (
        intelligence.prometheus_router,
        intelligence.knowledge_router,
        intelligence.ai_router,
    ):
        api.include_router(router)
    app.include_router(api)
    app.include_router(health.router)
    return app
