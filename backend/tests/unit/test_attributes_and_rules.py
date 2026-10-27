from uuid import uuid4

import pytest

from app.core.exceptions import BusinessRuleError, ConflictError
from app.core.permissions import ROLE_PERMISSIONS, Permission, Role, has_permission
from app.domain.agents.entities import AgentRole, DutyStatus
from app.domain.agents.rules import (
    ensure_duty_change_allowed,
    ensure_role_compatible,
    ensure_vehicle_assignable,
)
from app.domain.equipment.entities import EquipmentCategory, EquipmentType
from app.domain.equipment.status import EquipmentStatus
from app.domain.organizations import OrganizationKind
from app.schemas.equipment_attributes import (
    ATTRIBUTE_SCHEMAS,
    attributes_json_schema,
    validate_attributes,
)

VIATURA = EquipmentType(
    "viatura", "Viatura", EquipmentCategory.FROTA_OPERACIONAL, "car", True, True, "viatura"
)
CAMERA = EquipmentType(
    "camera", "Câmera", EquipmentCategory.MONITORAMENTO, "cctv", False, False, "camera"
)


class TestAttributes:
    def test_speed_radar_requires_max_speed(self) -> None:
        with pytest.raises(BusinessRuleError) as error:
            validate_attributes("radar", {"enforcement_types": ["velocidade"]})
        assert error.value.extra["errors"]

    def test_red_light_radar_rejects_max_speed(self) -> None:
        with pytest.raises(BusinessRuleError):
            validate_attributes(
                "radar", {"enforcement_types": ["avanco_semaforo"], "max_speed_kmh": 60}
            )

    def test_valid_camera_is_normalized_with_defaults(self) -> None:
        result = validate_attributes("camera", {"resolution": "4k", "night_vision": True})
        assert result["color_mode"] == "colorida"
        assert result["ptz"] is False

    def test_unknown_field_is_rejected_for_typed_schemas(self) -> None:
        with pytest.raises(BusinessRuleError):
            validate_attributes("camera", {"resolution": "4k", "night_vision": True, "x": 1})

    def test_scooter_speed_follows_contran_limit(self) -> None:
        base = {"ownership": "publico", "battery_capacity_wh": 500}
        validate_attributes("patinete", {**base, "max_speed_kmh": 32})
        with pytest.raises(BusinessRuleError):
            validate_attributes("patinete", {**base, "max_speed_kmh": 40})

    @pytest.mark.parametrize("plate", ["ABC1D23", "abc-1234", "BRA2E19"])
    def test_plates_accept_old_and_mercosul_formats(self, plate: str) -> None:
        result = validate_attributes("moto_agente", {"plate": plate, "engine_cc": 300})
        assert result["plate"] == plate.upper().replace("-", "")

    def test_invalid_plate_is_rejected(self) -> None:
        with pytest.raises(BusinessRuleError):
            validate_attributes("moto_agente", {"plate": "12345678", "engine_cc": 300})

    def test_mototaxi_carries_exactly_one_passenger(self) -> None:
        data = {
            "service": "mototaxi",
            "plate": "ABC1D23",
            "permit_number": "A1",
            "passenger_capacity": 2,
        }
        with pytest.raises(BusinessRuleError):
            validate_attributes("veiculo_transporte", data)

    def test_free_attributes_accept_only_scalars(self) -> None:
        assert validate_attributes("outro", {"descricao": "PMV", "largura": 3.5}) == {
            "descricao": "PMV",
            "largura": 3.5,
        }
        with pytest.raises(BusinessRuleError):
            validate_attributes("outro", {"lista": [1, 2]})

    @pytest.mark.parametrize("schema_key", sorted(ATTRIBUTE_SCHEMAS))
    def test_every_schema_exposes_json_schema_for_dynamic_forms(self, schema_key: str) -> None:
        assert attributes_json_schema(schema_key)["type"] == "object"


class TestAgentRules:
    def test_traffic_agent_cannot_belong_to_military_police(self) -> None:
        with pytest.raises(BusinessRuleError):
            ensure_role_compatible(AgentRole.AGENTE_TRANSITO, OrganizationKind.POLICIA_MILITAR)

    def test_role_outro_is_compatible_with_any_organization(self) -> None:
        for kind in OrganizationKind:
            ensure_role_compatible(AgentRole.OUTRO, kind)

    def test_vehicle_crew_capacity_is_enforced(self) -> None:
        org = uuid4()
        kwargs = {
            "vehicle_type": VIATURA,
            "vehicle_status": EquipmentStatus.OPERACIONAL,
            "vehicle_organization_id": org,
            "vehicle_attributes": {"crew_capacity": 2},
            "agent_organization_id": org,
        }
        ensure_vehicle_assignable(**kwargs, other_active_crew=1)
        with pytest.raises(ConflictError):
            ensure_vehicle_assignable(**kwargs, other_active_crew=2)

    def test_only_vehicles_of_same_organization_can_be_assigned(self) -> None:
        with pytest.raises(BusinessRuleError):
            ensure_vehicle_assignable(
                vehicle_type=VIATURA,
                vehicle_status=EquipmentStatus.OPERACIONAL,
                vehicle_organization_id=uuid4(),
                vehicle_attributes={},
                agent_organization_id=uuid4(),
                other_active_crew=0,
            )

    def test_non_vehicle_cannot_be_assigned(self) -> None:
        org = uuid4()
        with pytest.raises(BusinessRuleError):
            ensure_vehicle_assignable(
                vehicle_type=CAMERA,
                vehicle_status=EquipmentStatus.OPERACIONAL,
                vehicle_organization_id=org,
                vehicle_attributes={},
                agent_organization_id=org,
                other_active_crew=0,
            )

    def test_broken_vehicle_cannot_be_assigned(self) -> None:
        org = uuid4()
        with pytest.raises(BusinessRuleError):
            ensure_vehicle_assignable(
                vehicle_type=VIATURA,
                vehicle_status=EquipmentStatus.MAU_FUNCIONAMENTO,
                vehicle_organization_id=org,
                vehicle_attributes={},
                agent_organization_id=org,
                other_active_crew=0,
            )

    def test_inactive_agent_cannot_go_on_duty(self) -> None:
        with pytest.raises(BusinessRuleError):
            ensure_duty_change_allowed(False, DutyStatus.FORA_DE_SERVICO, DutyStatus.EM_PATRULHA)

    def test_same_duty_status_is_a_conflict(self) -> None:
        with pytest.raises(ConflictError):
            ensure_duty_change_allowed(True, DutyStatus.DISPONIVEL, DutyStatus.DISPONIVEL)


class TestPermissions:
    def test_admin_has_every_permission(self) -> None:
        assert ROLE_PERMISSIONS[Role.ADMIN] == frozenset(Permission)

    def test_roles_are_cumulative(self) -> None:
        assert ROLE_PERMISSIONS[Role.CONSULTA] < ROLE_PERMISSIONS[Role.OPERADOR]
        assert ROLE_PERMISSIONS[Role.OPERADOR] < ROLE_PERMISSIONS[Role.GESTOR]
        assert ROLE_PERMISSIONS[Role.GESTOR] < ROLE_PERMISSIONS[Role.ADMIN]

    @pytest.mark.parametrize(
        ("role", "permission", "expected"),
        [
            (Role.CONSULTA, Permission.EQUIPMENT_READ, True),
            (Role.CONSULTA, Permission.EQUIPMENT_STATUS_CHANGE, False),
            (Role.OPERADOR, Permission.EQUIPMENT_STATUS_CHANGE, True),
            (Role.OPERADOR, Permission.EQUIPMENT_WRITE, False),
            (Role.GESTOR, Permission.EQUIPMENT_DELETE, True),
            (Role.GESTOR, Permission.USER_MANAGE, False),
        ],
    )
    def test_permission_matrix(self, role: Role, permission: Permission, expected: bool) -> None:
        assert has_permission(role, permission) is expected
