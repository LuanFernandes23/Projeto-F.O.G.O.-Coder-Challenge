"""Geradores determinísticos de equipamentos e agentes de demonstração."""

import math
import random
import string
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.domain.shared import UF, Address, GeoPoint
from app.seed.marilia_data import (
    CENTRO_RADIUS_KM,
    CITY,
    CITY_RADIUS_KM,
    FIRST_NAMES,
    LANDMARKS,
    LAST_NAMES,
    REGIONS,
    RegionSpec,
    offset_point,
)

REGIONS_BY_CODE = {region.code: region for region in REGIONS}


@dataclass(frozen=True, slots=True)
class Placement:
    region: RegionSpec
    address: Address
    location: GeoPoint


@dataclass(frozen=True, slots=True)
class EquipmentSpec:
    index: int
    type_code: str
    organization: str  # sigla
    brand: str
    model: str
    serial_number: str
    placement: Placement
    attributes: dict[str, Any]
    plan_interval_days: int | None
    failure_mean_days: float  # tempo médio entre falhas (antes do fator da região)
    theft_probability: float  # chance de furto ao longo da simulação


def random_point(rng: random.Random, region: RegionSpec) -> GeoPoint:
    if region.bearing_start is None or region.bearing_end is None:
        distance = CENTRO_RADIUS_KM * math.sqrt(rng.random()) * 0.97
        bearing = rng.uniform(0, 360)
    else:
        distance = rng.uniform(CENTRO_RADIUS_KM * 1.05, CITY_RADIUS_KM * 0.9)
        bearing = rng.uniform(region.bearing_start + 2, region.bearing_end - 2)
    lat, lng = offset_point(distance, bearing)
    return GeoPoint(latitude=round(lat, 6), longitude=round(lng, 6))


def random_reference(rng: random.Random, street: str, region: RegionSpec) -> str:
    if street.startswith("Rodovia"):
        return f"KM {rng.randint(440, 470)}"
    number = rng.randint(10, 3500)
    options = (
        f"número {number}",
        f"oposto ao número {number}",
        "S/N",
        f"em frente ao {rng.choice(LANDMARKS)}",
        f"esquina com {rng.choice(region.streets)}",
    )
    return rng.choices(options, weights=(5, 2, 1, 2, 2))[0]


def random_placement(rng: random.Random, region: RegionSpec) -> Placement:
    street = rng.choice(region.streets)
    address = Address(
        cep=f"{region.cep_prefix}{rng.randint(0, 999):03d}",
        street=street,
        reference=random_reference(rng, street, region),
        neighborhood=rng.choice(region.neighborhoods),
        city=CITY,
        uf=UF.SP,
    )
    return Placement(region, address, random_point(rng, region))


def random_plate(rng: random.Random) -> str:
    letters = "".join(rng.choices(string.ascii_uppercase, k=3))
    return f"{letters}{rng.randint(0, 9)}{rng.choice(string.ascii_uppercase)}{rng.randint(10, 99)}"


def person_name(rng: random.Random) -> str:
    return f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)} {rng.choice(LAST_NAMES)}"


# ---- atributos por tipo (sempre válidos para os schemas de app.schemas.equipment_attributes)


def _camera(rng: random.Random) -> dict[str, Any]:
    return {
        "resolution": rng.choice(["1080p", "1080p", "2k", "4k"]),
        "night_vision": rng.random() < 0.8,
        "color_mode": "colorida" if rng.random() < 0.9 else "preto_e_branco",
        "ptz": rng.random() < 0.35,
        "field_of_view_degrees": rng.choice([90, 110, 120, 360]),
        "recording_retention_days": rng.choice([15, 30, 60]),
        "video_analytics": rng.random() < 0.4,
    }


def _radar(rng: random.Random) -> dict[str, Any]:
    kinds = rng.choice(
        [
            ["velocidade"],
            ["velocidade", "avanco_semaforo"],
            ["avanco_semaforo"],
            ["parada_sobre_faixa", "avanco_semaforo"],
            ["conversao_proibida"],
            ["retorno_proibido"],
            ["faixa_exclusiva"],
        ]
    )
    return {
        "enforcement_types": kinds,
        "max_speed_kmh": rng.choice([40, 50, 60, 80]) if "velocidade" in kinds else None,
        "monitored_lanes": rng.randint(1, 4),
        "direction": rng.choice(["Centro → Bairro", "Bairro → Centro", "Ambos os sentidos"]),
        "plate_recognition": rng.random() < 0.7,
    }


def _traffic_light(rng: random.Random) -> dict[str, Any]:
    return {
        "phases": rng.choice([2, 3, 4, 6]),
        "pedestrian_button": rng.random() < 0.4,
        "countdown_timer": rng.random() < 0.5,
        "adaptive": rng.random() < 0.25,
        "battery_backup": rng.random() < 0.45,
    }


def _kiosk(rng: random.Random) -> dict[str, Any]:
    methods = rng.sample(["pix", "cartao_credito", "cartao_debito", "dinheiro", "aproximacao"], 3)
    return {
        "payment_methods": methods,
        "connectivity": rng.choice(["4g", "4g", "5g", "fibra"]),
        "receipt_printer": rng.random() < 0.8,
        "solar_powered": rng.random() < 0.3,
    }


def _scooter(rng: random.Random) -> dict[str, Any]:
    return {
        "ownership": "compartilhado" if rng.random() < 0.8 else "publico",
        "operator_name": "MOVE Compartilhados",
        "battery_capacity_wh": rng.choice([474, 551, 700]),
        "max_speed_kmh": rng.choice([20, 25, 32]),
        "gps_tracker": True,
    }


def _barrier(rng: random.Random) -> dict[str, Any]:
    return {
        "access_control_methods": rng.sample(["tag_rfid", "leitura_de_placa", "ticket"], 2),
        "opening_time_seconds": rng.choice([1.5, 2.0, 3.0]),
        "vehicle_loop_detector": True,
    }


def _scale(rng: random.Random) -> dict[str, Any]:
    return {
        "scale_kind": rng.choice(["estatica", "dinamica"]),
        "max_capacity_tonnes": rng.choice([60.0, 80.0, 100.0]),
        "monitored_lanes": rng.randint(1, 2),
    }


def _autonomous(rng: random.Random) -> dict[str, Any]:
    return {
        "plate": random_plate(rng),
        "autonomy_hours": rng.choice([8.0, 10.0, 12.0]),
        "camera_count": rng.choice([4, 6, 8]),
        "plate_recognition": True,
    }


def _transport(rng: random.Random) -> dict[str, Any]:
    service = rng.choices(["taxi", "mototaxi", "escolar"], weights=(5, 3, 3))[0]
    capacity = {"taxi": 4, "mototaxi": 1, "escolar": rng.choice([15, 20, 28])}[service]
    return {
        "service": service,
        "plate": random_plate(rng),
        "permit_number": f"ALV-{rng.randint(1000, 9999)}",
        "passenger_capacity": capacity,
        "wheelchair_accessible": service == "escolar" and rng.random() < 0.4,
    }


def _motorcycle(rng: random.Random) -> dict[str, Any]:
    return {
        "plate": random_plate(rng),
        "engine_cc": rng.choice([250, 300, 310]),
        "siren": True,
        "radio": True,
        "crew_capacity": 1,
    }


def _patrol(rng: random.Random) -> dict[str, Any]:
    return {
        "plate": random_plate(rng),
        "prefix": f"VTR-{rng.randint(100, 999)}",
        "crew_capacity": rng.choice([2, 2, 4]),
        "onboard_camera": rng.random() < 0.6,
        "armored": False,
    }


def _other(rng: random.Random) -> dict[str, Any]:
    return {
        "descricao": "Painel de mensagens variáveis",
        "largura_m": rng.choice([3.0, 4.5]),
        "leds_coloridos": True,
    }


@dataclass(frozen=True, slots=True)
class TypeProfile:
    type_code: str
    count: int
    organizations: tuple[str, ...]
    brands: tuple[tuple[str, str], ...]  # (marca, modelo)
    attributes: Callable[[random.Random], dict[str, Any]]
    region_weights: dict[str, float]
    plan_interval_days: int | None
    failure_mean_days: float
    theft_probability: float = 0.0
    base_region: str | None = None  # equipamentos móveis: base fixa


_EVEN = {"centro": 1.0, "norte": 1.0, "leste": 1.0, "sul": 1.0, "oeste": 1.0}
_CENTRAL = {"centro": 3.0, "norte": 1.0, "leste": 1.2, "sul": 1.0, "oeste": 0.8}

TYPE_PROFILES: tuple[TypeProfile, ...] = (
    TypeProfile(
        "camera",
        70,
        ("GCM", "GCM", "PMESP", "SEMOB"),
        (
            ("Intelbras", "VIP 5450 Z"),
            ("Hikvision", "DS-2DE4425IW"),
            ("Dahua", "SD49425XB"),
            ("Axis", "Q6075-E"),
        ),
        _camera,
        _CENTRAL,
        180,
        260,
        theft_probability=0.02,
    ),
    TypeProfile(
        "radar",
        40,
        ("SEMOB",),
        (("Perkons", "PK-RV 4"), ("Pumatronix", "ITSCAM 600"), ("Velsis", "VS-R2")),
        _radar,
        _EVEN,
        120,
        300,
    ),
    TypeProfile(
        "semaforo",
        35,
        ("SEMOB",),
        (("Tesc", "MC-2000"), ("Digicon", "CTA-8"), ("Engebras", "CS-16")),
        _traffic_light,
        _CENTRAL,
        90,
        220,
    ),
    TypeProfile(
        "totem_estacionamento",
        25,
        ("ZONA AZUL",),
        (("Gertec", "GPOS-T"), ("ZonaTech", "ZT-300")),
        _kiosk,
        {"centro": 5.0, "leste": 1.0, "sul": 0.6},
        60,
        160,
        theft_probability=0.01,
    ),
    TypeProfile(
        "patinete",
        40,
        ("MOVE",),
        (("Segway-Ninebot", "Max G30"), ("Xiaomi", "Scooter 4 Pro")),
        _scooter,
        _CENTRAL,
        45,
        110,
        theft_probability=0.12,
    ),
    TypeProfile(
        "cancela",
        10,
        ("SEMOB", "ZONA AZUL"),
        (("PPA", "Barrier Pro"), ("Garen", "CI-500")),
        _barrier,
        {"centro": 2.0, "oeste": 1.0},
        90,
        200,
    ),
    TypeProfile(
        "balanca",
        4,
        ("DER",),
        (("Toledo", "9091"), ("Filizola", "ID-30T")),
        _scale,
        {"oeste": 1.0},
        180,
        400,
    ),
    TypeProfile(
        "veiculo_fiscalizacao_autonomo",
        4,
        ("ZONA AZUL",),
        (("Pumatronix", "Patrulha Autônoma PA-1"),),
        _autonomous,
        {"centro": 1.0},
        30,
        150,
        base_region="centro",
    ),
    TypeProfile(
        "veiculo_transporte",
        30,
        ("SEMOB",),
        (("Chevrolet", "Spin"),),  # marca/modelo final depende do serviço
        _transport,
        _EVEN,
        180,
        365,
    ),
    TypeProfile(
        "moto_agente",
        18,
        ("SEMOB",),
        (("Honda", "XRE 300"), ("Yamaha", "Lander 250")),
        _motorcycle,
        {"centro": 1.0},
        90,
        280,
        base_region="centro",
    ),
    TypeProfile(
        "viatura",
        20,
        ("GCM", "PMESP"),
        (("Toyota", "Hilux"), ("Chevrolet", "Trailblazer"), ("Renault", "Duster")),
        _patrol,
        {"centro": 1.0},
        60,
        240,
        base_region="centro",
    ),
    TypeProfile(
        "outro",
        4,
        ("SEMOB",),
        (("Engebras", "PMV-LED"),),
        _other,
        {"centro": 1.0, "norte": 1.0},
        None,
        400,
    ),
)

_TRANSPORT_MODELS: dict[str, tuple[tuple[str, str], ...]] = {
    "taxi": (("Chevrolet", "Spin"), ("Fiat", "Cronos"), ("Toyota", "Corolla")),
    "mototaxi": (("Honda", "CG 160"), ("Yamaha", "Factor 150")),
    "escolar": (("Volkswagen", "Volare"), ("Mercedes-Benz", "Sprinter")),
}

_BASE_PLACEMENTS: dict[str, Placement] = {}


def _base_placement(rng: random.Random, organization: str, region_code: str) -> Placement:
    key = f"{organization}:{region_code}"
    if key not in _BASE_PLACEMENTS:
        _BASE_PLACEMENTS[key] = random_placement(rng, REGIONS_BY_CODE[region_code])
    return _BASE_PLACEMENTS[key]


def generate_equipment_specs(seed: int) -> list[EquipmentSpec]:
    rng = random.Random(seed)
    _BASE_PLACEMENTS.clear()
    specs: list[EquipmentSpec] = []
    for profile in TYPE_PROFILES:
        regions = list(profile.region_weights)
        weights = list(profile.region_weights.values())
        for _ in range(profile.count):
            organization = profile.organizations[len(specs) % len(profile.organizations)]
            attributes = profile.attributes(rng)
            brand, model = rng.choice(
                _TRANSPORT_MODELS.get(attributes.get("service", ""), profile.brands)
            )
            if profile.base_region:
                placement = _base_placement(rng, organization, profile.base_region)
            else:
                region = REGIONS_BY_CODE[rng.choices(regions, weights=weights)[0]]
                placement = random_placement(rng, region)
            index = len(specs) + 1
            specs.append(
                EquipmentSpec(
                    index=index,
                    type_code=profile.type_code,
                    organization=organization,
                    brand=brand,
                    model=model,
                    serial_number=f"{brand[:3].upper()}-{2024 + index % 3}-{index:06d}",
                    placement=placement,
                    attributes=attributes,
                    plan_interval_days=profile.plan_interval_days,
                    failure_mean_days=profile.failure_mean_days,
                    theft_probability=profile.theft_probability,
                )
            )
    return specs
