"""Fábricas de serviços por requisição (injeção de dependências do FastAPI)."""

from typing import Annotated

from fastapi import Depends

from app.agent.runtime import PrometheusRuntime, build_gateway
from app.ai.crypto import SecretBox
from app.api.dependencies.container import AppContainer, get_container
from app.integrations.cep.base import CepProvider
from app.integrations.cep.brasilapi_client import BrasilApiCepClient
from app.integrations.cep.viacep_client import ViaCepClient
from app.repositories.unit_of_work import SqlAlchemyUnitOfWork
from app.services.address_service import AddressLookupService
from app.services.agent_service import AgentService
from app.services.ai_settings_service import AiSettingsService
from app.services.alert_service import AlertService
from app.services.dispatch_service import DispatchService
from app.services.equipment_lifecycle import EquipmentLifecycle
from app.services.equipment_service import EquipmentService
from app.services.maintenance_service import MaintenanceService
from app.services.operations_service import OperationsQueryService
from app.services.prediction_service import PredictionService
from app.services.reference_service import (
    EquipmentTypeService,
    OrganizationService,
    RegionService,
)
from app.services.telemetry_service import TelemetryService
from app.services.user_service import AuthService, UserService

Container = Annotated[AppContainer, Depends(get_container)]


def _uow(container: AppContainer) -> SqlAlchemyUnitOfWork:
    return SqlAlchemyUnitOfWork(container.session_factory)


def get_auth_service(container: Container) -> AuthService:
    return AuthService(
        _uow(container), container.clock, container.password_hasher, container.token_service
    )


def get_user_service(container: Container) -> UserService:
    return UserService(_uow(container), container.clock, container.password_hasher)


def get_organization_service(container: Container) -> OrganizationService:
    return OrganizationService(_uow(container), container.clock)


def get_region_service(container: Container) -> RegionService:
    return RegionService(_uow(container))


def get_equipment_type_service(container: Container) -> EquipmentTypeService:
    return EquipmentTypeService(_uow(container))


def get_equipment_service(container: Container) -> EquipmentService:
    return EquipmentService(
        _uow(container),
        container.clock,
        EquipmentLifecycle(),
        container.settings.maintenance_due_soon_days,
    )


def get_maintenance_service(container: Container) -> MaintenanceService:
    return MaintenanceService(_uow(container), container.clock, EquipmentLifecycle())


def get_agent_service(container: Container) -> AgentService:
    return AgentService(_uow(container), container.clock)


def get_alert_service(container: Container) -> AlertService:
    return AlertService(_uow(container), container.clock)


def get_operations_service(container: Container) -> OperationsQueryService:
    settings = container.settings
    return OperationsQueryService(
        _uow(container), container.clock, settings.maintenance_due_soon_days, settings.timezone
    )


def get_dispatch_service(container: Container) -> DispatchService:
    return DispatchService(_uow(container), container.clock)


def get_telemetry_service(container: Container) -> TelemetryService:
    return TelemetryService(_uow(container), container.clock, EquipmentLifecycle())


def get_prediction_service(container: Container) -> PredictionService:
    return PredictionService(_uow(container), container.clock, container.settings.tz)


async def get_prometheus_runtime(container: Container) -> PrometheusRuntime:
    return await container.prometheus_runtime()


def get_ai_settings_service(container: Container) -> AiSettingsService:
    settings = container.settings
    gateway = build_gateway(container.session_factory, container.clock, settings)
    return AiSettingsService(
        _uow(container),
        container.clock,
        SecretBox(
            settings.ai_encryption_key.get_secret_value(),
            settings.jwt_secret_key.get_secret_value(),
        ),
        gateway,
        container.http_client,
        settings.ai_timeout_seconds,
    )


def get_address_service(container: Container) -> AddressLookupService:
    settings = container.settings
    providers: list[CepProvider] = [
        ViaCepClient(container.http_client, settings.viacep_base_url),
        BrasilApiCepClient(container.http_client, settings.brasilapi_base_url),
    ]
    return AddressLookupService(providers, container.cep_cache)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
UserServiceDep = Annotated[UserService, Depends(get_user_service)]
OrganizationServiceDep = Annotated[OrganizationService, Depends(get_organization_service)]
RegionServiceDep = Annotated[RegionService, Depends(get_region_service)]
EquipmentTypeServiceDep = Annotated[EquipmentTypeService, Depends(get_equipment_type_service)]
EquipmentServiceDep = Annotated[EquipmentService, Depends(get_equipment_service)]
MaintenanceServiceDep = Annotated[MaintenanceService, Depends(get_maintenance_service)]
AgentServiceDep = Annotated[AgentService, Depends(get_agent_service)]
AddressServiceDep = Annotated[AddressLookupService, Depends(get_address_service)]
AlertServiceDep = Annotated[AlertService, Depends(get_alert_service)]
OperationsServiceDep = Annotated[OperationsQueryService, Depends(get_operations_service)]
DispatchServiceDep = Annotated[DispatchService, Depends(get_dispatch_service)]
TelemetryServiceDep = Annotated[TelemetryService, Depends(get_telemetry_service)]
PredictionServiceDep = Annotated[PredictionService, Depends(get_prediction_service)]
PrometheusRuntimeDep = Annotated[PrometheusRuntime, Depends(get_prometheus_runtime)]
AiSettingsServiceDep = Annotated[AiSettingsService, Depends(get_ai_settings_service)]
