"""Características específicas por tipo de equipamento (modelo híbrido).

Os atributos ficam em JSONB no banco, mas cada tipo conhecido tem um schema Pydantic
estrito (``extra="forbid"``) que valida a entrada e gera o JSON Schema exposto em
``GET /equipment-types``, a partir do qual o front monta o formulário dinâmico.
O tipo ``outro`` aceita atributos livres, para os equipamentos "entre outros".
"""

import re
from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Any, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.core.exceptions import BusinessRuleError
from app.schemas.attribute_labels import add_enum_labels, field_title

_PLATE_PATTERN = re.compile(
    r"^[A-Z]{3}-?\d[A-Z0-9]\d{2}$"
)  # antigo (ABC-1234) e Mercosul (ABC1D23)

# Resolução 996/2023 do CONTRAN: patinetes elétricos limitados a 32 km/h.
SCOOTER_MAX_SPEED_KMH = 32


class _StrictAttributes(BaseModel):
    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, field_title_generator=field_title
    )


def _normalize_plate(value: str | None) -> str | None:
    if value is None:
        return None
    plate = value.upper().replace(" ", "")
    if not _PLATE_PATTERN.match(plate):
        raise ValueError("Placa inválida. Use o padrão antigo (ABC-1234) ou Mercosul (ABC1D23).")
    return plate.replace("-", "")


Plate = Annotated[str, Field(min_length=7, max_length=8, examples=["BRA2E19"])]


class RadarSubtype(StrEnum):
    VELOCIDADE = "velocidade"
    AVANCO_SEMAFORO = "avanco_semaforo"
    RETORNO_PROIBIDO = "retorno_proibido"
    CONVERSAO_PROIBIDA = "conversao_proibida"
    PARADA_SOBRE_FAIXA = "parada_sobre_faixa"
    FAIXA_EXCLUSIVA = "faixa_exclusiva"


class RadarAttributes(_StrictAttributes):
    enforcement_types: list[RadarSubtype] = Field(
        min_length=1, description="O que o radar fiscaliza (pode acumular funções)."
    )
    max_speed_kmh: int | None = Field(
        default=None, ge=10, le=140, description="Obrigatória quando fiscaliza velocidade."
    )
    monitored_lanes: int = Field(default=1, ge=1, le=8)
    direction: str | None = Field(default=None, max_length=80, examples=["Centro → Bairro"])
    plate_recognition: bool = Field(
        default=False, description="Leitura automática de placas (OCR)."
    )

    @model_validator(mode="after")
    def _speed_required_for_speed_enforcement(self) -> Self:
        enforces_speed = RadarSubtype.VELOCIDADE in self.enforcement_types
        if enforces_speed and self.max_speed_kmh is None:
            raise ValueError("Informe a velocidade máxima para radares de velocidade.")
        if not enforces_speed and self.max_speed_kmh is not None:
            raise ValueError("Velocidade máxima só se aplica a radares de velocidade.")
        return self


class CameraResolution(StrEnum):
    HD_720P = "720p"
    FULL_HD_1080P = "1080p"
    QHD_2K = "2k"
    UHD_4K = "4k"


class ColorMode(StrEnum):
    COLORIDA = "colorida"
    PRETO_E_BRANCO = "preto_e_branco"


class CameraAttributes(_StrictAttributes):
    resolution: CameraResolution
    night_vision: bool
    color_mode: ColorMode = ColorMode.COLORIDA
    ptz: bool = Field(default=False, description="Movimento pan/tilt/zoom remoto.")
    field_of_view_degrees: int | None = Field(default=None, ge=10, le=360)
    recording_retention_days: int | None = Field(default=None, ge=1, le=365)
    video_analytics: bool = Field(default=False, description="Analítico embarcado (contagem, LPR).")


class ScaleKind(StrEnum):
    ESTATICA = "estatica"
    DINAMICA = "dinamica"  # pesagem em movimento (WIM)


class TruckScaleAttributes(_StrictAttributes):
    scale_kind: ScaleKind
    max_capacity_tonnes: float = Field(gt=0, le=200)
    monitored_lanes: int = Field(default=1, ge=1, le=6)


class AutonomousEnforcementVehicleAttributes(_StrictAttributes):
    plate: Plate
    autonomy_hours: float = Field(gt=0, le=48)
    camera_count: int = Field(ge=1, le=16)
    plate_recognition: bool = True

    _normalize = field_validator("plate")(_normalize_plate)


class AccessControlMethod(StrEnum):
    TAG_RFID = "tag_rfid"
    LEITURA_DE_PLACA = "leitura_de_placa"
    TICKET = "ticket"
    MANUAL = "manual"


class BarrierGateAttributes(_StrictAttributes):
    access_control_methods: list[AccessControlMethod] = Field(min_length=1)
    opening_time_seconds: float = Field(gt=0, le=30)
    vehicle_loop_detector: bool = True


class TransportService(StrEnum):
    TAXI = "taxi"
    MOTOTAXI = "mototaxi"
    ESCOLAR = "escolar"


class TransportVehicleAttributes(_StrictAttributes):
    service: TransportService
    plate: Plate
    permit_number: str = Field(min_length=1, max_length=30, description="Número do alvará.")
    passenger_capacity: int = Field(ge=1, le=60)
    wheelchair_accessible: bool = False

    _normalize = field_validator("plate")(_normalize_plate)

    @model_validator(mode="after")
    def _mototaxi_carries_one(self) -> Self:
        if self.service is TransportService.MOTOTAXI and self.passenger_capacity != 1:
            raise ValueError("Mototáxi transporta exatamente 1 passageiro.")
        return self


class PaymentMethod(StrEnum):
    PIX = "pix"
    CARTAO_CREDITO = "cartao_credito"
    CARTAO_DEBITO = "cartao_debito"
    DINHEIRO = "dinheiro"
    APROXIMACAO = "aproximacao"


class Connectivity(StrEnum):
    G4 = "4g"
    G5 = "5g"
    WIFI = "wifi"
    FIBRA = "fibra"


class ParkingKioskAttributes(_StrictAttributes):
    payment_methods: list[PaymentMethod] = Field(min_length=1)
    connectivity: Connectivity
    receipt_printer: bool = True
    solar_powered: bool = False


class ScooterOwnership(StrEnum):
    PUBLICO = "publico"
    COMPARTILHADO = "compartilhado"


class ElectricScooterAttributes(_StrictAttributes):
    ownership: ScooterOwnership
    operator_name: str | None = Field(default=None, max_length=80)
    battery_capacity_wh: int = Field(gt=0, le=2000)
    max_speed_kmh: int = Field(gt=0, le=SCOOTER_MAX_SPEED_KMH)
    gps_tracker: bool = True


class AgentMotorcycleAttributes(_StrictAttributes):
    plate: Plate
    engine_cc: int = Field(ge=50, le=1500)
    siren: bool = True
    radio: bool = True
    crew_capacity: int = Field(default=1, ge=1, le=2)

    _normalize = field_validator("plate")(_normalize_plate)


class PatrolVehicleAttributes(_StrictAttributes):
    plate: Plate
    prefix: str = Field(min_length=1, max_length=20, description="Prefixo da viatura.")
    crew_capacity: int = Field(default=2, ge=1, le=6)
    onboard_camera: bool = False
    armored: bool = False

    _normalize = field_validator("plate")(_normalize_plate)


class TrafficLightControllerAttributes(_StrictAttributes):
    phases: int = Field(ge=2, le=16)
    pedestrian_button: bool = False
    countdown_timer: bool = False
    adaptive: bool = Field(default=False, description="Ajusta tempos conforme o fluxo.")
    battery_backup: bool = Field(default=False, description="Nobreak para queda de energia.")


AttributeValue = str | int | float | bool | None


class OtherAttributes(BaseModel):
    """Atributos livres (pares chave/valor simples) para tipos sem schema próprio."""

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="after")
    def _only_scalar_values(self) -> Self:
        extras = self.model_extra or {}
        if len(extras) > 30:
            raise ValueError("Informe no máximo 30 atributos.")
        for key, value in extras.items():
            if not isinstance(value, AttributeValue):
                raise ValueError(f"O atributo '{key}' deve ser texto, número ou booleano.")
        return self


ATTRIBUTE_SCHEMAS: Mapping[str, type[BaseModel]] = {
    "radar": RadarAttributes,
    "camera": CameraAttributes,
    "balanca": TruckScaleAttributes,
    "veiculo_fiscalizacao_autonomo": AutonomousEnforcementVehicleAttributes,
    "cancela": BarrierGateAttributes,
    "veiculo_transporte": TransportVehicleAttributes,
    "totem_estacionamento": ParkingKioskAttributes,
    "patinete": ElectricScooterAttributes,
    "moto_agente": AgentMotorcycleAttributes,
    "viatura": PatrolVehicleAttributes,
    "semaforo": TrafficLightControllerAttributes,
    "outro": OtherAttributes,
}


def attributes_json_schema(schema_key: str) -> dict[str, Any]:
    return add_enum_labels(ATTRIBUTE_SCHEMAS[schema_key].model_json_schema())


def validate_attributes(schema_key: str, attributes: Mapping[str, Any]) -> dict[str, Any]:
    """Valida e normaliza os atributos; erros viram 422 com a lista de campos inválidos."""
    schema = ATTRIBUTE_SCHEMAS.get(schema_key)
    if schema is None:
        raise BusinessRuleError(f"Schema de atributos '{schema_key}' desconhecido.")
    try:
        model = schema.model_validate(dict(attributes))
    except ValidationError as exc:
        raise BusinessRuleError(
            "Características do equipamento inválidas para o tipo informado.",
            extra={
                "errors": [
                    {"field": ".".join(str(p) for p in err["loc"]) or None, "message": err["msg"]}
                    for err in exc.errors(include_url=False)
                ]
            },
        ) from exc
    return model.model_dump(mode="json")
