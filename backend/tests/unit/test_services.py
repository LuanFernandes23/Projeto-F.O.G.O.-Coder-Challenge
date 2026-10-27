"""Casos de uso com repositórios em memória: regras de orquestração sem banco."""

from datetime import date, datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest

from app.core.clock import ManualClock
from app.core.exceptions import (
    BusinessRuleError,
    ConflictError,
    InvalidStatusTransitionError,
    VersionConflictError,
)
from app.domain.agents.entities import AgentRole, DutyStatus
from app.domain.equipment.status import EquipmentStatus
from app.domain.maintenance.entities import (
    MaintenanceKind,
    MaintenanceNeed,
    MaintenanceOrderStatus,
    MaintenancePriority,
)
from app.domain.organizations import OrganizationKind, OrganizationUsage
from app.domain.shared import UF, Address, GeoPoint
from app.services.agent_service import AgentChanges, AgentService, NewAgent
from app.services.equipment_lifecycle import EquipmentLifecycle
from app.services.equipment_service import (
    EquipmentChanges,
    EquipmentService,
    NewEquipment,
    PlanSpec,
)
from app.services.maintenance_service import MaintenanceService, NewMaintenanceOrder
from app.services.reference_service import OrganizationService
from tests.unit.fakes import FakeUnitOfWork

TZ = ZoneInfo("America/Sao_Paulo")
ADDRESS = Address("17500000", "Avenida Sampaio Vidal", "número 181", "Centro", "Marília", UF.SP)
POINT = GeoPoint(-22.2139, -49.9458)
CAMERA = {"resolution": "4k", "night_vision": True}


@pytest.fixture
def uow() -> FakeUnitOfWork:
    return FakeUnitOfWork()


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock(datetime(2026, 10, 1, 12, tzinfo=TZ), TZ)


@pytest.fixture
def org_id(uow: FakeUnitOfWork) -> UUID:
    return uow.organizations.seed(OrganizationKind.TRANSITO, "SEMOB").id


@pytest.fixture
def equipment_service(uow: FakeUnitOfWork, clock: ManualClock) -> EquipmentService:
    return EquipmentService(uow, clock, EquipmentLifecycle(), due_soon_days=7)


@pytest.fixture
def maintenance_service(uow: FakeUnitOfWork, clock: ManualClock) -> MaintenanceService:
    return MaintenanceService(uow, clock, EquipmentLifecycle())


def _new(org_id: UUID, **overrides: object) -> NewEquipment:
    data: dict[str, object] = {
        "type_code": "camera",
        "serial_number": "CAM-001",
        "brand": "Intelbras",
        "model": "VIP",
        "organization_id": org_id,
        "status": EquipmentStatus.OPERACIONAL,
        "installed_on": date(2026, 9, 1),
        "address": ADDRESS,
        "location": POINT,
        "attributes": CAMERA,
        "maintenance_plan": None,
    }
    data.update(overrides)
    return NewEquipment(**data)  # type: ignore[arg-type]


class TestEquipmentRegistration:
    async def test_create_records_initial_history_and_region(
        self, equipment_service: EquipmentService, uow: FakeUnitOfWork, org_id: UUID
    ) -> None:
        view = await equipment_service.create(_new(org_id), actor_id=None)
        assert view.record.region is not None
        assert [e.to_status for e in uow.equipment_history.entries] == [EquipmentStatus.OPERACIONAL]
        assert view.record.equipment.attributes["color_mode"] == "colorida"

    async def test_create_broken_equipment_opens_immediate_corrective_order(
        self, equipment_service: EquipmentService, uow: FakeUnitOfWork, org_id: UUID
    ) -> None:
        view = await equipment_service.create(
            _new(org_id, status=EquipmentStatus.MAU_FUNCIONAMENTO), actor_id=None
        )
        orders = list(uow.maintenance_orders.items.values())
        assert len(orders) == 1
        assert orders[0].priority is MaintenancePriority.IMEDIATA
        assert view.maintenance.need is MaintenanceNeed.IMEDIATA

    async def test_plan_defaults_next_due_date_to_today_plus_interval(
        self, equipment_service: EquipmentService, org_id: UUID
    ) -> None:
        view = await equipment_service.create(
            _new(org_id, maintenance_plan=PlanSpec(30, None)), actor_id=None
        )
        assert view.maintenance.next_maintenance_date == date(2026, 10, 31)
        assert view.maintenance.need is MaintenanceNeed.AGENDADA

    async def test_duplicate_brand_and_serial_is_a_conflict(
        self, equipment_service: EquipmentService, org_id: UUID
    ) -> None:
        await equipment_service.create(_new(org_id), actor_id=None)
        with pytest.raises(ConflictError):
            await equipment_service.create(_new(org_id, serial_number="cam-001"), actor_id=None)

    async def test_invalid_attributes_are_rejected(
        self, equipment_service: EquipmentService, org_id: UUID
    ) -> None:
        with pytest.raises(BusinessRuleError):
            await equipment_service.create(_new(org_id, attributes={"resolution": "8k"}), None)

    async def test_unknown_type_is_rejected(
        self, equipment_service: EquipmentService, org_id: UUID
    ) -> None:
        with pytest.raises(BusinessRuleError):
            await equipment_service.create(_new(org_id, type_code="disco_voador"), None)

    async def test_stale_version_on_update_is_rejected(
        self, equipment_service: EquipmentService, org_id: UUID
    ) -> None:
        view = await equipment_service.create(_new(org_id), actor_id=None)
        equipment_id = view.record.equipment.id
        await equipment_service.update(equipment_id, EquipmentChanges(version=1, model="X"), None)
        with pytest.raises(VersionConflictError):
            await equipment_service.update(
                equipment_id, EquipmentChanges(version=1, model="Y"), None
            )


class TestStatusLifecycle:
    async def test_failure_opens_order_and_theft_cancels_it(
        self, equipment_service: EquipmentService, uow: FakeUnitOfWork, org_id: UUID
    ) -> None:
        view = await equipment_service.create(
            _new(org_id, maintenance_plan=PlanSpec(30, None)), actor_id=None
        )
        equipment_id = view.record.equipment.id

        failed = await equipment_service.change_status(
            equipment_id, EquipmentStatus.MAU_FUNCIONAMENTO, "Sem imagem", None
        )
        assert failed.maintenance.need is MaintenanceNeed.IMEDIATA

        stolen = await equipment_service.change_status(
            equipment_id, EquipmentStatus.FURTADO, "Furto registrado", None
        )
        orders = list(uow.maintenance_orders.items.values())
        assert all(o.status is MaintenanceOrderStatus.CANCELADA for o in orders)
        # plano suspenso: furtado não aparece como "manutenção vencida/agendada"
        assert stolen.maintenance.need is MaintenanceNeed.NENHUMA
        assert [e.to_status for e in uow.equipment_history.entries][-2:] == [
            EquipmentStatus.MAU_FUNCIONAMENTO,
            EquipmentStatus.FURTADO,
        ]

    async def test_invalid_transition_leaves_no_trace(
        self, equipment_service: EquipmentService, uow: FakeUnitOfWork, org_id: UUID
    ) -> None:
        view = await equipment_service.create(
            _new(org_id, status=EquipmentStatus.NAO_INSTALADO, installed_on=None), None
        )
        with pytest.raises(InvalidStatusTransitionError):
            await equipment_service.change_status(
                view.record.equipment.id, EquipmentStatus.FURTADO, "teste", None
            )
        assert len(uow.equipment_history.entries) == 1

    async def test_installing_sets_installation_date_to_today(
        self, equipment_service: EquipmentService, org_id: UUID
    ) -> None:
        view = await equipment_service.create(
            _new(org_id, status=EquipmentStatus.NAO_INSTALADO, installed_on=None), None
        )
        installed = await equipment_service.change_status(
            view.record.equipment.id, EquipmentStatus.OPERACIONAL, "Instalado", None
        )
        assert installed.record.equipment.installed_on == date(2026, 10, 1)


class TestMaintenanceFlow:
    async def _broken(self, service: EquipmentService, org_id: UUID) -> UUID:
        view = await service.create(_new(org_id, maintenance_plan=PlanSpec(90, None)), None)
        equipment_id = view.record.equipment.id
        await service.change_status(equipment_id, EquipmentStatus.MAU_FUNCIONAMENTO, "Queda", None)
        return equipment_id

    async def test_order_lifecycle_drives_equipment_status(
        self,
        equipment_service: EquipmentService,
        maintenance_service: MaintenanceService,
        uow: FakeUnitOfWork,
        org_id: UUID,
    ) -> None:
        equipment_id = await self._broken(equipment_service, org_id)
        order = next(iter(uow.maintenance_orders.items.values()))

        await maintenance_service.transition_order(
            order.id, MaintenanceOrderStatus.EM_ANDAMENTO, None, None
        )
        assert uow.equipment.items[equipment_id].status is EquipmentStatus.EM_MANUTENCAO

        await maintenance_service.transition_order(
            order.id, MaintenanceOrderStatus.CONCLUIDA, "ok", None
        )
        equipment = uow.equipment.items[equipment_id]
        assert equipment.status is EquipmentStatus.OPERACIONAL
        assert equipment.maintenance_need is MaintenanceNeed.AGENDADA

    async def test_completing_preventive_advances_the_plan(
        self,
        equipment_service: EquipmentService,
        maintenance_service: MaintenanceService,
        uow: FakeUnitOfWork,
        clock: ManualClock,
        org_id: UUID,
    ) -> None:
        view = await equipment_service.create(
            _new(org_id, maintenance_plan=PlanSpec(90, None)), None
        )
        equipment_id = view.record.equipment.id
        order = await maintenance_service.open_order(
            equipment_id,
            NewMaintenanceOrder(
                MaintenanceKind.PREVENTIVA, MaintenancePriority.AGENDADA, "prev", None
            ),
            None,
        )
        await maintenance_service.transition_order(
            order.id, MaintenanceOrderStatus.EM_ANDAMENTO, None, None
        )
        clock.advance(timedelta(days=2))
        await maintenance_service.transition_order(
            order.id, MaintenanceOrderStatus.CONCLUIDA, None, None
        )
        plan = uow.maintenance_plans.items[equipment_id]
        assert plan.last_done_on == date(2026, 10, 3)
        assert plan.next_due_date == date(2026, 10, 3) + timedelta(days=90)

    async def test_equipment_stays_in_maintenance_while_other_work_is_in_progress(
        self,
        equipment_service: EquipmentService,
        maintenance_service: MaintenanceService,
        uow: FakeUnitOfWork,
        org_id: UUID,
    ) -> None:
        equipment_id = await self._broken(equipment_service, org_id)
        corrective = next(iter(uow.maintenance_orders.items.values()))
        preventive = await maintenance_service.open_order(
            equipment_id,
            NewMaintenanceOrder(
                MaintenanceKind.PREVENTIVA, MaintenancePriority.AGENDADA, "prev", None
            ),
            None,
        )
        for order_id in (corrective.id, preventive.id):
            await maintenance_service.transition_order(
                order_id, MaintenanceOrderStatus.EM_ANDAMENTO, None, None
            )
        await maintenance_service.transition_order(
            corrective.id, MaintenanceOrderStatus.CONCLUIDA, None, None
        )
        assert uow.equipment.items[equipment_id].status is EquipmentStatus.EM_MANUTENCAO

    async def test_cannot_open_two_open_orders_of_same_kind(
        self,
        equipment_service: EquipmentService,
        maintenance_service: MaintenanceService,
        org_id: UUID,
    ) -> None:
        equipment_id = await self._broken(equipment_service, org_id)
        with pytest.raises(ConflictError):
            await maintenance_service.open_order(
                equipment_id,
                NewMaintenanceOrder(
                    MaintenanceKind.CORRETIVA, MaintenancePriority.IMEDIATA, "x", None
                ),
                None,
            )

    async def test_preventive_job_is_idempotent(
        self,
        equipment_service: EquipmentService,
        maintenance_service: MaintenanceService,
        uow: FakeUnitOfWork,
        clock: ManualClock,
        org_id: UUID,
    ) -> None:
        await equipment_service.create(_new(org_id, maintenance_plan=PlanSpec(10, None)), None)
        clock.advance(timedelta(days=11))
        assert await maintenance_service.open_due_preventive_orders() == 1
        assert await maintenance_service.open_due_preventive_orders() == 0
        orders = list(uow.maintenance_orders.items.values())
        assert [o.kind for o in orders] == [MaintenanceKind.PREVENTIVA]

    async def test_preventive_job_skips_when_lock_is_taken(
        self, maintenance_service: MaintenanceService, uow: FakeUnitOfWork
    ) -> None:
        uow.job_locks.available = False
        assert await maintenance_service.open_due_preventive_orders() == 0


class TestAgents:
    @pytest.fixture
    def agent_service(self, uow: FakeUnitOfWork, clock: ManualClock) -> AgentService:
        return AgentService(uow, clock)

    def _agent(self, org_id: UUID, **overrides: object) -> NewAgent:
        data: dict[str, object] = {
            "full_name": "Ana Paula Ribeiro",
            "registration_number": "SEMOB-0001",
            "role": AgentRole.AGENTE_TRANSITO,
            "organization_id": org_id,
            "duty_status": DutyStatus.FORA_DE_SERVICO,
            "base_address": ADDRESS,
            "base_location": POINT,
            "assigned_vehicle_id": None,
        }
        data.update(overrides)
        return NewAgent(**data)  # type: ignore[arg-type]

    async def _motorcycle(self, service: EquipmentService, org_id: UUID) -> UUID:
        view = await service.create(
            _new(
                org_id,
                type_code="moto_agente",
                serial_number=f"MOTO-{uuid4().hex[:6]}",
                attributes={"plate": "ABC1D23", "engine_cc": 300},
            ),
            None,
        )
        return view.record.equipment.id

    async def test_role_must_match_organization(
        self, agent_service: AgentService, uow: FakeUnitOfWork
    ) -> None:
        pm = uow.organizations.seed(OrganizationKind.POLICIA_MILITAR, "PM")
        with pytest.raises(BusinessRuleError):
            await agent_service.create(self._agent(pm.id), None)

    async def test_motorcycle_fits_a_single_agent(
        self, agent_service: AgentService, equipment_service: EquipmentService, org_id: UUID
    ) -> None:
        moto = await self._motorcycle(equipment_service, org_id)
        await agent_service.create(self._agent(org_id, assigned_vehicle_id=moto), None)
        with pytest.raises(ConflictError):
            await agent_service.create(
                self._agent(org_id, registration_number="SEMOB-0002", assigned_vehicle_id=moto),
                None,
            )

    async def test_vehicle_with_crew_cannot_be_reported_stolen(
        self, agent_service: AgentService, equipment_service: EquipmentService, org_id: UUID
    ) -> None:
        moto = await self._motorcycle(equipment_service, org_id)
        await agent_service.create(self._agent(org_id, assigned_vehicle_id=moto), None)
        with pytest.raises(ConflictError):
            await equipment_service.change_status(moto, EquipmentStatus.FURTADO, "furto", None)

    async def test_deactivation_ends_duty_and_releases_vehicle(
        self,
        agent_service: AgentService,
        equipment_service: EquipmentService,
        uow: FakeUnitOfWork,
        org_id: UUID,
    ) -> None:
        moto = await self._motorcycle(equipment_service, org_id)
        record = await agent_service.create(self._agent(org_id, assigned_vehicle_id=moto), None)
        agent_id = record.agent.id
        on_duty = await agent_service.change_duty_status(
            agent_id, DutyStatus.EM_PATRULHA, None, None
        )

        updated = await agent_service.update(
            agent_id, AgentChanges(version=on_duty.agent.version, is_active=False), None
        )
        assert updated.agent.duty_status is DutyStatus.FORA_DE_SERVICO
        assert updated.agent.assigned_vehicle_id is None
        assert uow.agent_history.entries[-1].reason == "Agente desativado"

    async def test_duplicate_registration_in_same_organization(
        self, agent_service: AgentService, org_id: UUID
    ) -> None:
        await agent_service.create(self._agent(org_id), None)
        with pytest.raises(ConflictError):
            await agent_service.create(self._agent(org_id, full_name="Outra Pessoa"), None)


class TestOrganizationService:
    async def test_lists_usage_and_blocks_deleting_organization_in_use(
        self, uow: FakeUnitOfWork, clock: ManualClock
    ) -> None:
        service = OrganizationService(uow, clock)
        used = uow.organizations.seed(OrganizationKind.GUARDA_MUNICIPAL, "GCM")
        free = uow.organizations.seed(OrganizationKind.OUTRO, "LIVRE")
        uow.organizations.usage_by_id[used.id] = OrganizationUsage(equipment=3, agents=2)

        usage = dict((o.acronym, u) for o, u in await service.list_with_usage())
        assert usage["GCM"] == OrganizationUsage(3, 2)
        assert usage["LIVRE"] == OrganizationUsage()

        with pytest.raises(ConflictError):
            await service.delete(used.id)
        await service.delete(free.id)
        assert free.id not in uow.organizations.items

    async def test_rejects_duplicate_acronym_and_normalizes_case(
        self, uow: FakeUnitOfWork, clock: ManualClock
    ) -> None:
        service = OrganizationService(uow, clock)
        created = await service.create("Defesa Civil", "dc", OrganizationKind.OUTRO)
        assert created.acronym == "DC"
        with pytest.raises(ConflictError):
            await service.create("Outra Defesa", "DC", OrganizationKind.OUTRO)
