"""Elementos compartilhados entre as rotas: paginação e documentação de erros."""

from typing import Annotated, Any

from fastapi import Depends, Query

from app.domain.shared import PageRequest
from app.schemas.common import ProblemDetail


def page_params(
    limit: Annotated[int, Query(ge=1, le=500, description="Itens por página.")] = 50,
    offset: Annotated[int, Query(ge=0, description="Deslocamento.")] = 0,
) -> PageRequest:
    return PageRequest(limit=limit, offset=offset)


Pagination = Annotated[PageRequest, Depends(page_params)]


def problems(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    descriptions = {
        401: "Não autenticado",
        403: "Sem permissão",
        404: "Não encontrado",
        409: "Conflito de estado",
        422: "Dados inválidos ou regra de negócio violada",
        502: "Falha em serviço externo",
        503: "Serviço externo indisponível",
    }
    return {
        code: {
            "model": ProblemDetail,
            "description": descriptions[code],
            "content": {"application/problem+json": {}},
        }
        for code in status_codes
    }


AUTH_PROBLEMS = problems(401, 403)
