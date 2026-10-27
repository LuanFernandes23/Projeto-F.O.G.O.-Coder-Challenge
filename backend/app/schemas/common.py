"""Contratos genéricos: paginação e erro padronizado (RFC 9457)."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PageOutput[T](BaseModel):
    items: list[T]
    total: int = Field(description="Total de registros que atendem aos filtros.")
    limit: int
    offset: int


class ProblemDetail(BaseModel):
    """Erro no formato ``application/problem+json`` (RFC 9457)."""

    model_config = ConfigDict(extra="allow")

    type: str = Field(examples=["https://fogo.local/problems/conflito"])
    title: str
    status: int
    detail: str
    instance: str | None = None
    code: str
    request_id: str | None = None


class StatusOption(BaseModel):
    code: str
    label: str
    allowed_transitions: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
