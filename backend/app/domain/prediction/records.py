"""Registros persistidos do motor preditivo (objetos simples, desacoplados do ORM)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class ModelRun:
    id: int
    fitted_at: datetime
    params: dict[str, Any]
    metrics: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Snapshot:
    kind: str
    generated_at: datetime
    payload: dict[str, Any]
