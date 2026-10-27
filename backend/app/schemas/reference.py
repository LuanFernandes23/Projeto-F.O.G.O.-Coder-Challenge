"""Contratos de dados de referência: órgãos, regiões e tipos de equipamento."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domain.equipment.entities import EquipmentCategory
from app.domain.organizations import OrganizationKind


class OrganizationCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=3, max_length=150, examples=["Guarda Civil Municipal"])
    acronym: str = Field(min_length=2, max_length=20, examples=["GCM"])
    kind: OrganizationKind


class OrganizationUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=3, max_length=150)
    acronym: str | None = Field(default=None, min_length=2, max_length=20)
    kind: OrganizationKind | None = None


class OrganizationOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    acronym: str
    kind: OrganizationKind
    created_at: datetime
    updated_at: datetime


class OrganizationListItemOutput(OrganizationOutput):
    equipment_count: int = Field(description="Equipamentos vinculados ao órgão.")
    agent_count: int = Field(description="Agentes vinculados ao órgão.")
    in_use: bool = Field(description="Com vínculos o órgão não pode ser excluído.")


class OrganizationSummaryOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    acronym: str
    kind: OrganizationKind


class RegionOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    geometry: dict[str, Any] | None = Field(
        default=None, description="Polígono em GeoJSON (apenas com include_geometry=true)."
    )


class RegionSummaryOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str


class EquipmentTypeCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(pattern=r"^[a-z][a-z0-9_]{2,49}$", examples=["painel_mensagem_variavel"])
    name: str = Field(min_length=3, max_length=120)
    category: EquipmentCategory
    icon: str = Field(min_length=2, max_length=40, examples=["sign"])
    is_mobile: bool = False
    description: str | None = Field(default=None, max_length=300)


class EquipmentTypeOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    category: EquipmentCategory
    icon: str
    is_mobile: bool
    is_vehicle: bool
    description: str | None
    attributes_schema: dict[str, Any] = Field(
        description="JSON Schema das características específicas deste tipo."
    )


class EquipmentTypeSummaryOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    category: EquipmentCategory
    icon: str
