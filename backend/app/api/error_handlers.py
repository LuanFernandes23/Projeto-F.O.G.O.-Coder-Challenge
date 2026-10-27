"""Conversão de exceções em respostas ``application/problem+json`` (RFC 9457)."""

import logging
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import AppError
from app.core.logging import request_id_var

logger = logging.getLogger(__name__)

_PROBLEM_BASE = "https://fogo.dev/problems/"
_MEDIA_TYPE = "application/problem+json"


def _problem(
    request: Request,
    *,
    status: int,
    code: str,
    title: str,
    detail: str,
    extra: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"{_PROBLEM_BASE}{code}",
        "title": title,
        "status": status,
        "detail": detail,
        "instance": request.url.path,
        "code": code,
        "request_id": request_id_var.get(),
    }
    if extra:
        body.update(extra)
    return JSONResponse(body, status_code=status, media_type=_MEDIA_TYPE, headers=headers)


async def _app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    exc = cast("AppError", exc)
    if exc.status_code >= 500:
        logger.error("Erro de integração", extra={"code": exc.code, "detail": exc.detail})
    headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
    return _problem(
        request,
        status=exc.status_code,
        code=exc.code,
        title=exc.title,
        detail=exc.detail,
        extra=exc.extra,
        headers=headers,
    )


async def _validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    exc = cast("RequestValidationError", exc)
    errors = [
        {
            "field": ".".join(str(part) for part in err["loc"] if part != "body") or None,
            "message": err["msg"],
            "type": err["type"],
        }
        for err in exc.errors()
    ]
    return _problem(
        request,
        status=422,
        code="dados_invalidos",
        title="Dados inválidos",
        detail="Um ou mais campos não passaram na validação.",
        extra={"errors": errors},
    )


async def _http_error_handler(request: Request, exc: Exception) -> JSONResponse:
    exc = cast("StarletteHTTPException", exc)
    return _problem(
        request,
        status=exc.status_code,
        code=f"http_{exc.status_code}",
        title=str(exc.detail),
        detail=str(exc.detail),
        headers=dict(exc.headers) if exc.headers else None,
    )


async def _unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "Erro inesperado",
        extra={"path": request.url.path, "method": request.method, "error": type(exc).__name__},
    )
    return _problem(
        request,
        status=500,
        code="erro_interno",
        title="Erro interno",
        detail="Ocorreu um erro inesperado. Informe o request_id ao suporte.",
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_error_handler)
    app.add_exception_handler(Exception, _unexpected_error_handler)
