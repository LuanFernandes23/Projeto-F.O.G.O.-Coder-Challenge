"""Órgãos responsáveis por equipamentos e agentes."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class OrganizationKind(StrEnum):
    TRANSITO = "transito"
    GUARDA_MUNICIPAL = "guarda_municipal"
    POLICIA_MILITAR = "policia_militar"
    CONCESSIONARIA = "concessionaria"
    OUTRO = "outro"


@dataclass(slots=True)
class Organization:
    id: UUID
    name: str
    acronym: str
    kind: OrganizationKind
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class OrganizationUsage:
    """Quantos equipamentos e agentes estão vinculados ao órgão (impede a exclusão)."""

    equipment: int = 0
    agents: int = 0

    @property
    def in_use(self) -> bool:
        return self.equipment > 0 or self.agents > 0


@dataclass(frozen=True, slots=True)
class OrganizationSummary:
    id: UUID
    name: str
    acronym: str
    kind: OrganizationKind
