"""Regiões da cidade (polígonos) usadas para agrupar e filtrar a operação."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RegionSummary:
    id: UUID
    code: str
    name: str


@dataclass(frozen=True, slots=True)
class Region:
    id: UUID
    code: str
    name: str
    geometry: dict[str, Any] | None  # GeoJSON, carregado apenas quando solicitado
