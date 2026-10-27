"""Unidade de trabalho: uma sessão/transação por operação de negócio.

Commit só acontece quando o serviço chama ``commit()`` após concluir toda a operação;
qualquer exceção (ou saída sem commit) resulta em rollback.
"""

import logging
from types import TracebackType
from typing import Self

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositories.agent_repository import SqlAgentRepository, SqlAgentStatusHistoryRepository
from app.repositories.ai_repository import SqlAiRepository
from app.repositories.alert_repository import SqlAlertRepository
from app.repositories.dispatch_repository import SqlDispatchRepository
from app.repositories.equipment_repository import (
    SqlEquipmentRepository,
    SqlEquipmentStatusHistoryRepository,
)
from app.repositories.event_publisher import PgEventPublisher
from app.repositories.knowledge_repository import SqlKnowledgeRepository
from app.repositories.maintenance_repository import (
    SqlMaintenanceOrderRepository,
    SqlMaintenancePlanRepository,
)
from app.repositories.operations_repository import SqlOperationsRepository
from app.repositories.prediction_repository import SqlPredictionRepository
from app.repositories.prometheus_repository import SqlPrometheusRepository
from app.repositories.reference_repositories import (
    SqlEquipmentTypeRepository,
    SqlOrganizationRepository,
    SqlRegionRepository,
)
from app.repositories.sql_helpers import translate_integrity_error
from app.repositories.telemetry_repository import SqlTelemetryRepository
from app.repositories.user_repository import SqlUserRepository

logger = logging.getLogger(__name__)


class SqlJobLockRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def try_acquire(self, lock_key: int) -> bool:
        result = await self._session.execute(select(func.pg_try_advisory_xact_lock(lock_key)))
        return bool(result.scalar_one())


class SqlAlchemyUnitOfWork:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> Self:
        session = self._session_factory()
        self._session = session
        self.users = SqlUserRepository(session)
        self.organizations = SqlOrganizationRepository(session)
        self.regions = SqlRegionRepository(session)
        self.equipment_types = SqlEquipmentTypeRepository(session)
        self.equipment = SqlEquipmentRepository(session)
        self.equipment_history = SqlEquipmentStatusHistoryRepository(session)
        self.maintenance_plans = SqlMaintenancePlanRepository(session)
        self.maintenance_orders = SqlMaintenanceOrderRepository(session)
        self.agents = SqlAgentRepository(session)
        self.agent_history = SqlAgentStatusHistoryRepository(session)
        self.job_locks = SqlJobLockRepository(session)
        self.alerts = SqlAlertRepository(session)
        self.dispatches = SqlDispatchRepository(session)
        self.telemetry = SqlTelemetryRepository(session)
        self.operations = SqlOperationsRepository(session)
        self.events = PgEventPublisher(session)
        self.predictions = SqlPredictionRepository(session)
        self.knowledge = SqlKnowledgeRepository(session)
        self.ai = SqlAiRepository(session)
        self.prometheus = SqlPrometheusRepository(session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        session = self._require_session()
        try:
            await session.rollback()  # no-op após commit; desfaz tudo em caso de erro
        finally:
            await session.close()
            self._session = None
        if isinstance(exc, IntegrityError):
            raise translate_integrity_error(exc) from exc
        if isinstance(exc, SQLAlchemyError):
            logger.error("Erro de banco de dados", extra={"error_type": type(exc).__name__})

    async def commit(self) -> None:
        await self._require_session().commit()

    async def rollback(self) -> None:
        await self._require_session().rollback()

    def _require_session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("UnitOfWork usado fora do bloco 'async with'.")
        return self._session
