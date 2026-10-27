"""Dados estáticos de demonstração de Marília-SP.

Bairros e vias são inspirados na cidade, mas a divisão em zonas e as coordenadas são
APROXIMADAS (setores ao redor do centro) e órgãos, equipamentos e pessoas são fictícios:
servem apenas para demonstrar o sistema com volume e distribuição realistas.
"""

import math
from dataclasses import dataclass
from typing import Any

CITY = "Marília"
UF_CODE = "SP"
CENTER_LAT = -22.2139
CENTER_LNG = -49.9458

_KM_PER_DEG_LAT = 111.32
_KM_PER_DEG_LNG = 111.32 * math.cos(math.radians(CENTER_LAT))

CENTRO_RADIUS_KM = 1.6
CITY_RADIUS_KM = 7.0


@dataclass(frozen=True, slots=True)
class RegionSpec:
    code: str
    name: str
    bearing_start: float | None  # graus a partir do norte, sentido horário (None = centro)
    bearing_end: float | None
    neighborhoods: tuple[str, ...]
    streets: tuple[str, ...]
    cep_prefix: str
    risk_factor: float  # multiplicador de falhas/vandalismo (padrões para a Parte 3)


REGIONS: tuple[RegionSpec, ...] = (
    RegionSpec(
        "centro",
        "Centro",
        None,
        None,
        ("Centro", "Barbosa", "Fragata", "Alto Cafezal", "Vila São Miguel"),
        (
            "Avenida Sampaio Vidal",
            "Avenida Rio Branco",
            "Rua Nove de Julho",
            "Rua São Luiz",
            "Avenida Vicente Ferreira",
            "Rua Paraíba",
            "Rua Bahia",
            "Avenida Pedro de Toledo",
        ),
        "17500",
        1.0,
    ),
    RegionSpec(
        "norte",
        "Zona Norte",
        -45.0,
        45.0,
        (
            "Núcleo Habitacional Nova Marília",
            "Jardim Altos do Palmital",
            "Palmital",
            "Jardim Teotônio Vilela",
            "Jardim Marajó",
            "Parque São Jorge",
        ),
        (
            "Avenida República",
            "Avenida Brigadeiro Eduardo Gomes",
            "Avenida Nelson Spielmann",
            "Avenida Castro Alves",
        ),
        "17519",
        1.45,
    ),
    RegionSpec(
        "leste",
        "Zona Leste",
        45.0,
        135.0,
        (
            "Cascata",
            "Jardim Califórnia",
            "Jardim Universitário",
            "Jardim Cavallari",
            "Jardim Aquarius",
        ),
        (
            "Avenida das Esmeraldas",
            "Avenida Cascata",
            "Avenida Hygino Muzzy Filho",
            "Avenida Tiradentes",
        ),
        "17514",
        1.1,
    ),
    RegionSpec(
        "sul",
        "Zona Sul",
        135.0,
        225.0,
        (
            "Jardim Maria Izabel",
            "Jardim Tangará",
            "Parque das Esmeraldas",
            "Somenzari",
            "Jardim Acapulco",
            "Jardim Lavínia",
        ),
        (
            "Avenida Santo Antônio",
            "Avenida João Ramalho",
            "Avenida Saudade",
            "Rua Doutor Próspero Cecílio Coimbra",
            "Avenida Carlos Gomes",
        ),
        "17526",
        1.25,
    ),
    RegionSpec(
        "oeste",
        "Zona Oeste",
        225.0,
        315.0,
        ("Banzato", "Santa Antonieta", "Distrito Industrial", "Jardim Ohara", "Jardim Morumbi"),
        (
            "Avenida Yusaburo Sasazaki",
            "Avenida Monte Carmelo",
            "Avenida Feijó",
            "Rodovia SP-294 (Comandante João Ribeiro de Barros)",
        ),
        "17512",
        0.9,
    ),
)

LANDMARKS = (
    "Mercado do Tio",
    "Terminal Urbano",
    "Hospital",
    "Escola Estadual",
    "Praça da Matriz",
    "Shopping",
    "Rodoviária",
    "Posto de Saúde",
    "Ginásio Municipal",
    "Supermercado",
)


def offset_point(distance_km: float, bearing_deg: float) -> tuple[float, float]:
    """Ponto (lat, lng) a ``distance_km`` do centro no rumo ``bearing_deg``."""
    bearing = math.radians(bearing_deg)
    lat = CENTER_LAT + (distance_km * math.cos(bearing)) / _KM_PER_DEG_LAT
    lng = CENTER_LNG + (distance_km * math.sin(bearing)) / _KM_PER_DEG_LNG
    return lat, lng


def region_geojson(spec: RegionSpec, arc_points: int = 48) -> dict[str, Any]:
    """Centro = círculo; zonas = setores anulares (sem sobreposição entre si)."""
    if spec.bearing_start is None or spec.bearing_end is None:
        ring = [offset_point(CENTRO_RADIUS_KM, 360.0 * i / arc_points) for i in range(arc_points)]
    else:
        span = spec.bearing_end - spec.bearing_start
        outer = [
            offset_point(CITY_RADIUS_KM, spec.bearing_start + span * i / arc_points)
            for i in range(arc_points + 1)
        ]
        inner = [
            offset_point(CENTRO_RADIUS_KM, spec.bearing_end - span * i / arc_points)
            for i in range(arc_points + 1)
        ]
        ring = outer + inner
    coordinates = [[lng, lat] for lat, lng in ring]
    coordinates.append(coordinates[0])
    return {"type": "Polygon", "coordinates": [coordinates]}


ORGANIZATIONS = (
    ("SEMOB", "Secretaria Municipal de Mobilidade Urbana", "transito"),
    ("GCM", "Guarda Civil Municipal", "guarda_municipal"),
    ("PMESP", "Polícia Militar — Companhia de Marília", "policia_militar"),
    ("DER", "Departamento de Estradas — Regional Marília", "transito"),
    ("ZONA AZUL", "Concessionária do Estacionamento Rotativo", "concessionaria"),
    ("MOVE", "Operadora de Micromobilidade Compartilhada", "concessionaria"),
)

FIRST_NAMES = (
    "Ana",
    "Bruno",
    "Carla",
    "Diego",
    "Eduarda",
    "Felipe",
    "Gabriela",
    "Henrique",
    "Isabela",
    "João",
    "Karina",
    "Lucas",
    "Mariana",
    "Nathan",
    "Olívia",
    "Paulo",
    "Rafaela",
    "Rodrigo",
    "Sabrina",
    "Thiago",
    "Vanessa",
    "Vinícius",
    "Larissa",
    "Marcos",
    "Patrícia",
    "Renato",
    "Juliana",
    "Fernando",
    "Camila",
    "Gustavo",
    "Letícia",
    "André",
    "Beatriz",
    "Caio",
)
LAST_NAMES = (
    "Silva",
    "Santos",
    "Oliveira",
    "Souza",
    "Rodrigues",
    "Ferreira",
    "Alves",
    "Pereira",
    "Lima",
    "Gomes",
    "Costa",
    "Ribeiro",
    "Martins",
    "Carvalho",
    "Almeida",
    "Lopes",
    "Soares",
    "Fernandes",
    "Vieira",
    "Barbosa",
    "Rocha",
    "Dias",
    "Nascimento",
    "Moreira",
)

DEMO_USERS = (
    ("gestor@fogo.dev", "Gestora de Operações", "gestor"),
    ("operador@fogo.dev", "Operador da Central", "operador"),
    ("consulta@fogo.dev", "Analista (somente leitura)", "consulta"),
)
