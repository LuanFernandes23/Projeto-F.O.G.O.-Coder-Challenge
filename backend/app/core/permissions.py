"""RBAC: perfis de acesso e a matriz perfil → permissões.

A matriz é a única fonte de verdade de autorização; rotas declaram a permissão
exigida e nunca o perfil, então mudar quem pode o quê é uma alteração em um só lugar.
"""

from collections.abc import Mapping
from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    GESTOR = "gestor"
    OPERADOR = "operador"
    CONSULTA = "consulta"


class Permission(StrEnum):
    EQUIPMENT_READ = "equipment:read"
    EQUIPMENT_WRITE = "equipment:write"
    EQUIPMENT_DELETE = "equipment:delete"
    EQUIPMENT_STATUS_CHANGE = "equipment:status_change"
    MAINTENANCE_PLAN_WRITE = "maintenance:plan_write"
    MAINTENANCE_ORDER_OPERATE = "maintenance:order_operate"
    AGENT_READ = "agent:read"
    AGENT_WRITE = "agent:write"
    AGENT_DELETE = "agent:delete"
    AGENT_STATUS_CHANGE = "agent:status_change"
    ORGANIZATION_READ = "organization:read"
    ORGANIZATION_WRITE = "organization:write"
    REFERENCE_WRITE = "reference:write"
    USER_MANAGE = "user:manage"
    OPERATIONS_READ = "operations:read"
    ALERT_ACKNOWLEDGE = "alert:acknowledge"
    DISPATCH_MANAGE = "dispatch:manage"
    # Parte 3
    PROMETHEUS_APPROVE = "prometheus:approve"  # aprovar/rejeitar ações pedidas pelo agente
    PROMETHEUS_MANAGE = "prometheus:manage"  # modo, políticas de autonomia, recalcular modelos
    KNOWLEDGE_MANAGE = "knowledge:manage"  # base de conhecimento (documentos do RAG)
    AI_CONFIGURE = "ai:configure"  # provedor, modelo e chave de API (somente admin)


_READ_ONLY = frozenset(
    {
        Permission.EQUIPMENT_READ,
        Permission.AGENT_READ,
        Permission.ORGANIZATION_READ,
        Permission.OPERATIONS_READ,
    }
)
_OPERATOR = _READ_ONLY | {
    Permission.EQUIPMENT_STATUS_CHANGE,
    Permission.MAINTENANCE_ORDER_OPERATE,
    Permission.AGENT_STATUS_CHANGE,
    Permission.ALERT_ACKNOWLEDGE,
    Permission.DISPATCH_MANAGE,
    Permission.PROMETHEUS_APPROVE,
}
_MANAGER = _OPERATOR | {
    Permission.EQUIPMENT_WRITE,
    Permission.EQUIPMENT_DELETE,
    Permission.MAINTENANCE_PLAN_WRITE,
    Permission.AGENT_WRITE,
    Permission.AGENT_DELETE,
    Permission.ORGANIZATION_WRITE,
    Permission.REFERENCE_WRITE,
    Permission.PROMETHEUS_MANAGE,
    Permission.KNOWLEDGE_MANAGE,
}

ROLE_PERMISSIONS: Mapping[Role, frozenset[Permission]] = {
    Role.CONSULTA: _READ_ONLY,
    Role.OPERADOR: frozenset(_OPERATOR),
    Role.GESTOR: frozenset(_MANAGER),
    Role.ADMIN: frozenset(Permission),
}


def has_permission(role: Role, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS[role]
