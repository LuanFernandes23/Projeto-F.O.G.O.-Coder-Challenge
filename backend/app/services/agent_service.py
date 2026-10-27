"""Casos de uso de agentes de campo."""

import logging
import uuid
from dataclasses import dataclass, replace
from uuid import UUID

from app.core.clock import Clock
from app.core.exceptions import (
    BusinessRuleError,
    ConflictError,
    NotFoundError,
    VersionConflictError,
)
from app.domain.agents.entities import (
    Agent,
    AgentFilters,
    AgentRecord,
    AgentRole,
    AgentStatusChange,
    DutyStatus,
)
from app.domain.agents.rules import (
    ensure_duty_change_allowed,
    ensure_role_compatible,
    ensure_vehicle_assignable,
)
from app.domain.operations.events import DomainEvent, EventType
from app.domain.shared import Address, GeoPoint, Page, PageRequest
from app.services.ports import UnitOfWork

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class NewAgent:
    full_name: str
    registration_number: str
    role: AgentRole
    organization_id: UUID
    duty_status: DutyStatus
    base_address: Address
    base_location: GeoPoint
    assigned_vehicle_id: UUID | None


@dataclass(frozen=True, slots=True)
class AgentChanges:
    version: int
    full_name: str | None = None
    registration_number: str | None = None
    role: AgentRole | None = None
    organization_id: UUID | None = None
    is_active: bool | None = None
    base_address: Address | None = None
    base_location: GeoPoint | None = None
    assigned_vehicle_id: UUID | None = None
    unassign_vehicle: bool = False


class AgentService:
    def __init__(self, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def create(self, data: NewAgent, actor_id: UUID | None) -> AgentRecord:
        now = self._clock.now()
        async with self._uow as uow:
            await self._ensure_role_matches_organization(uow, data.role, data.organization_id)
            await self._ensure_unique_registration(
                uow, data.organization_id, data.registration_number, None
            )
            agent = Agent(
                id=uuid.uuid4(),
                full_name=data.full_name,
                registration_number=data.registration_number,
                role=data.role,
                organization_id=data.organization_id,
                duty_status=data.duty_status,
                is_active=True,
                base_address=data.base_address,
                base_location=data.base_location,
                region_id=await uow.regions.find_covering(data.base_location),
                assigned_vehicle_id=None,
                version=1,
                created_at=now,
                updated_at=now,
            )
            if data.assigned_vehicle_id is not None:
                await self._ensure_vehicle(uow, data.assigned_vehicle_id, agent)
                agent.assigned_vehicle_id = data.assigned_vehicle_id
            await uow.agents.add(agent)
            await uow.agent_history.add(
                agent_id=agent.id,
                from_status=None,
                to_status=agent.duty_status,
                reason="Cadastro inicial",
                changed_by=actor_id,
                changed_at=now,
            )
            await uow.commit()
            logger.info("Agente cadastrado", extra={"agent_id": str(agent.id)})
            return await self._record(uow, agent.id)

    async def update(
        self, agent_id: UUID, changes: AgentChanges, actor_id: UUID | None
    ) -> AgentRecord:
        now = self._clock.now()
        async with self._uow as uow:
            agent = await self._require_active(uow, agent_id)
            if changes.version != agent.version:
                raise VersionConflictError(
                    "O agente foi alterado desde a última leitura. Recarregue e tente novamente.",
                    extra={"current_version": agent.version},
                )
            updated = await self._apply_changes(uow, agent, changes, actor_id)
            updated.updated_at = now
            updated.version = await uow.agents.update(updated)
            await uow.commit()
            return await self._record(uow, agent_id)

    async def archive(self, agent_id: UUID) -> None:
        now = self._clock.now()
        async with self._uow as uow:
            agent = await self._require_active(uow, agent_id)
            agent.archived_at = now
            agent.updated_at = now
            agent.is_active = False
            agent.assigned_vehicle_id = None
            await uow.agents.update(agent)
            await uow.commit()

    async def change_duty_status(
        self, agent_id: UUID, target: DutyStatus, reason: str | None, actor_id: UUID | None
    ) -> AgentRecord:
        now = self._clock.now()
        async with self._uow as uow:
            agent = await self._require_active(uow, agent_id)
            ensure_duty_change_allowed(agent.is_active, agent.duty_status, target)
            await uow.agent_history.add(
                agent_id=agent.id,
                from_status=agent.duty_status,
                to_status=target,
                reason=reason,
                changed_by=actor_id,
                changed_at=now,
            )
            agent.duty_status = target
            agent.updated_at = now
            await uow.agents.update(agent)
            await uow.events.publish(
                DomainEvent(
                    EventType.AGENT_STATUS_CHANGED,
                    {"id": str(agent.id), "duty_status": target.value},
                )
            )
            await uow.commit()
            return await self._record(uow, agent_id)

    async def get(self, agent_id: UUID) -> AgentRecord:
        async with self._uow as uow:
            return await self._record(uow, agent_id)

    async def search(self, filters: AgentFilters, page: PageRequest) -> Page[AgentRecord]:
        async with self._uow as uow:
            return await uow.agents.list_records(filters, page)

    async def status_history(self, agent_id: UUID, page: PageRequest) -> Page[AgentStatusChange]:
        async with self._uow as uow:
            if await uow.agents.get(agent_id) is None:
                raise NotFoundError("Agente não encontrado.")
            return await uow.agent_history.list_for_agent(agent_id, page)

    async def _apply_changes(
        self,
        uow: UnitOfWork,
        agent: Agent,
        changes: AgentChanges,
        actor_id: UUID | None,
    ) -> Agent:
        updated = replace(agent)
        if changes.full_name is not None:
            updated.full_name = changes.full_name
        if changes.registration_number is not None:
            updated.registration_number = changes.registration_number
        if changes.role is not None:
            updated.role = changes.role
        if changes.organization_id is not None:
            updated.organization_id = changes.organization_id
        if changes.base_address is not None:
            updated.base_address = changes.base_address
        if changes.base_location is not None:
            updated.base_location = changes.base_location
            updated.region_id = await uow.regions.find_covering(changes.base_location)

        if changes.role is not None or changes.organization_id is not None:
            await self._ensure_role_matches_organization(uow, updated.role, updated.organization_id)
        if changes.registration_number is not None or changes.organization_id is not None:
            await self._ensure_unique_registration(
                uow, updated.organization_id, updated.registration_number, agent.id
            )

        if changes.is_active is False and agent.is_active:
            await self._deactivate(uow, updated, actor_id)
        elif changes.is_active is True:
            updated.is_active = True

        if changes.unassign_vehicle:
            updated.assigned_vehicle_id = None
        elif changes.assigned_vehicle_id is not None:
            await self._ensure_vehicle(uow, changes.assigned_vehicle_id, updated)
            updated.assigned_vehicle_id = changes.assigned_vehicle_id
        elif updated.assigned_vehicle_id and updated.organization_id != agent.organization_id:
            raise BusinessRuleError(
                "Ao trocar de órgão, remova ou substitua a viatura atribuída ao agente."
            )
        return updated

    async def _deactivate(self, uow: UnitOfWork, agent: Agent, actor_id: UUID | None) -> None:
        """Desativar tira o agente de serviço e libera a viatura, com rastro no histórico."""
        now = self._clock.now()
        if agent.duty_status is not DutyStatus.FORA_DE_SERVICO:
            await uow.agent_history.add(
                agent_id=agent.id,
                from_status=agent.duty_status,
                to_status=DutyStatus.FORA_DE_SERVICO,
                reason="Agente desativado",
                changed_by=actor_id,
                changed_at=now,
            )
            agent.duty_status = DutyStatus.FORA_DE_SERVICO
        agent.is_active = False
        agent.assigned_vehicle_id = None

    @staticmethod
    async def _ensure_vehicle(uow: UnitOfWork, vehicle_id: UUID, agent: Agent) -> None:
        if not agent.is_active:
            raise BusinessRuleError("Agentes inativos não podem receber viatura.")
        vehicle = await uow.equipment.get(vehicle_id, for_update=True)
        if vehicle is None or vehicle.is_archived:
            raise BusinessRuleError(
                "Viatura não encontrada.", extra={"field": "assigned_vehicle_id"}
            )
        vehicle_type = await uow.equipment_types.get(vehicle.type_code)
        if vehicle_type is None:
            raise BusinessRuleError("Tipo da viatura não encontrado.")
        ensure_vehicle_assignable(
            vehicle_type=vehicle_type,
            vehicle_status=vehicle.status,
            vehicle_organization_id=vehicle.organization_id,
            vehicle_attributes=vehicle.attributes,
            agent_organization_id=agent.organization_id,
            other_active_crew=await uow.agents.count_active_crew(vehicle_id, agent.id),
        )

    @staticmethod
    async def _ensure_role_matches_organization(
        uow: UnitOfWork, role: AgentRole, organization_id: UUID
    ) -> None:
        organization = await uow.organizations.get(organization_id)
        if organization is None:
            raise BusinessRuleError("Órgão não encontrado.", extra={"field": "organization_id"})
        ensure_role_compatible(role, organization.kind)

    @staticmethod
    async def _ensure_unique_registration(
        uow: UnitOfWork, organization_id: UUID, registration_number: str, exclude_id: UUID | None
    ) -> None:
        if await uow.agents.exists_registration(organization_id, registration_number, exclude_id):
            raise ConflictError(
                "Já existe um agente ativo com esta matrícula neste órgão.",
                extra={"field": "registration_number"},
            )

    @staticmethod
    async def _require_active(uow: UnitOfWork, agent_id: UUID) -> Agent:
        agent = await uow.agents.get(agent_id, for_update=True)
        if agent is None or agent.archived_at is not None:
            raise NotFoundError("Agente não encontrado.")
        return agent

    @staticmethod
    async def _record(uow: UnitOfWork, agent_id: UUID) -> AgentRecord:
        record = await uow.agents.get_record(agent_id)
        if record is None or record.agent.archived_at is not None:
            raise NotFoundError("Agente não encontrado.")
        return record
