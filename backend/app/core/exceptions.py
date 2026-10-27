"""Hierarquia de exceções da aplicação.

Cada exceção carrega o status HTTP e um código estável, que o handler converte em
``application/problem+json`` (RFC 9457). Camadas internas não conhecem HTTP além desse mapa.
"""

from typing import Any


class AppError(Exception):
    status_code: int = 500
    code: str = "erro_interno"
    title: str = "Erro interno"

    def __init__(self, detail: str, *, extra: dict[str, Any] | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.extra = extra or {}


class NotFoundError(AppError):
    status_code = 404
    code = "recurso_nao_encontrado"
    title = "Recurso não encontrado"


class ConflictError(AppError):
    status_code = 409
    code = "conflito"
    title = "Conflito de estado"


class VersionConflictError(ConflictError):
    code = "versao_desatualizada"
    title = "O registro foi alterado por outra pessoa"


class InvalidStatusTransitionError(ConflictError):
    code = "transicao_de_situacao_invalida"
    title = "Transição de situação não permitida"


class BusinessRuleError(AppError):
    status_code = 422
    code = "regra_de_negocio_violada"
    title = "Regra de negócio violada"


class AuthenticationError(AppError):
    status_code = 401
    code = "nao_autenticado"
    title = "Autenticação necessária"


class PermissionDeniedError(AppError):
    status_code = 403
    code = "acesso_negado"
    title = "Acesso negado"


class IntegrationError(AppError):
    status_code = 502
    code = "falha_de_integracao"
    title = "Falha em serviço externo"


class IntegrationUnavailableError(AppError):
    status_code = 503
    code = "servico_externo_indisponivel"
    title = "Serviço externo indisponível"
