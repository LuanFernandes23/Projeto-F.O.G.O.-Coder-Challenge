"""Utilitários de persistência compartilhados pelos repositórios."""

from typing import Any

from geoalchemy2 import Geometry, WKTElement
from sqlalchemy import ColumnElement, cast, func
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictError
from app.domain.shared import Address, GeoPoint

# Mensagens amigáveis para violações de restrições conhecidas.
_CONSTRAINT_MESSAGES = {
    "uq_equipment_brand_serial_active": "Já existe equipamento ativo com esta marca e série.",
    "uq_agents_org_registration_active": "Já existe agente ativo com esta matrícula no órgão.",
    "uq_users_email_lower": "Já existe um usuário com este e-mail.",
    "uq_organizations_name_lower": "Já existe um órgão com este nome.",
    "uq_organizations_acronym_lower": "Já existe um órgão com esta sigla.",
    "uq_maintenance_orders_open_per_kind": "Já existe ordem aberta deste tipo para o equipamento.",
    "pk_equipment_types": "Já existe um tipo de equipamento com este código.",
    "uq_regions_code": "Já existe uma região com este código.",
}


def point_element(point: GeoPoint) -> WKTElement:
    return WKTElement(f"POINT({point.longitude} {point.latitude})", srid=4326)


def geography_point_literal(point: GeoPoint) -> ColumnElement[Any]:
    return func.ST_SetSRID(func.ST_MakePoint(point.longitude, point.latitude), 4326)


def latitude_of(column: Any) -> ColumnElement[float]:
    return func.ST_Y(cast(column, Geometry))


def longitude_of(column: Any) -> ColumnElement[float]:
    return func.ST_X(cast(column, Geometry))


def like_pattern(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def address_columns(address: Address) -> dict[str, Any]:
    return {
        "cep": address.cep,
        "street": address.street,
        "address_reference": address.reference,
        "neighborhood": address.neighborhood,
        "city": address.city,
        "uf": address.uf,
    }


def address_from_row(row: Any) -> Address:
    return Address(
        cep=row.cep,
        street=row.street,
        reference=row.address_reference,
        neighborhood=row.neighborhood,
        city=row.city,
        uf=row.uf,
    )


def translate_integrity_error(exc: IntegrityError) -> ConflictError:
    constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
    message = _CONSTRAINT_MESSAGES.get(constraint or "", "Operação conflita com dados existentes.")
    return ConflictError(message, extra={"constraint": constraint} if constraint else None)
