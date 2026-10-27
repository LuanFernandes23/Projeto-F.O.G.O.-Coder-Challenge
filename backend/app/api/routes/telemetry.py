"""Ingestão do gateway IoT (autenticação por chave, não por usuário)."""

import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Header

from app.api.dependencies.services import Container, TelemetryServiceDep
from app.api.routes.common import problems
from app.core.exceptions import AuthenticationError
from app.domain.operations.telemetry import AgentPositionReport, EquipmentHeartbeat
from app.domain.shared import GeoPoint
from app.schemas.location import GeoPointSchema
from app.schemas.operations import (
    AgentPositionBatchInput,
    HeartbeatBatchInput,
    IngestOutput,
    RegistryAgentOutput,
    RegistryDeviceOutput,
    RegistryOutput,
)


async def require_gateway_key(
    container: Container,
    x_gateway_key: Annotated[str | None, Header(description="Chave do gateway IoT.")] = None,
) -> None:
    expected = container.settings.iot_gateway_key.get_secret_value()
    # Comparação em tempo constante: não vaza a chave por timing.
    if not x_gateway_key or not secrets.compare_digest(x_gateway_key, expected):
        raise AuthenticationError("Chave de gateway ausente ou inválida (X-Gateway-Key).")


router = APIRouter(
    prefix="/telemetry",
    tags=["Telemetria IoT"],
    dependencies=[Depends(require_gateway_key)],
    responses=problems(401, 422),
)


@router.get("/registry", response_model=RegistryOutput, summary="Dispositivos e agentes conhecidos")
async def registry(service: TelemetryServiceDep) -> RegistryOutput:
    data = await service.registry()
    return RegistryOutput(
        devices=[
            RegistryDeviceOutput(
                equipment_id=d.equipment_id,
                type_code=d.type_code,
                status=d.status,
                lat=d.location.latitude,
                lng=d.location.longitude,
                region_code=d.region_code,
                intervention_since=d.intervention_since,
            )
            for d in data.devices
        ],
        agents=[
            RegistryAgentOutput(
                agent_id=a.agent_id,
                duty_status=a.duty_status,
                is_active=a.is_active,
                region_code=a.region_code,
                base=GeoPointSchema.from_domain(a.base),
                current=GeoPointSchema.from_domain(a.current) if a.current else None,
                vehicle_type=a.vehicle_type,
                dispatch_target=(
                    GeoPointSchema.from_domain(a.dispatch_target) if a.dispatch_target else None
                ),
            )
            for a in data.agents
        ],
    )


@router.post(
    "/equipment", response_model=IngestOutput, summary="Lote de heartbeats/métricas/falhas"
)
async def ingest_equipment(
    payload: HeartbeatBatchInput, service: TelemetryServiceDep
) -> IngestOutput:
    result = await service.ingest_equipment(
        [
            EquipmentHeartbeat(
                h.equipment_id, h.recorded_at, dict(h.metrics), h.fault, h.fault_averted
            )
            for h in payload.heartbeats
        ]
    )
    return IngestOutput(
        accepted=result.accepted, unknown=result.unknown, faults_registered=result.faults_registered
    )


@router.post("/agents", response_model=IngestOutput, summary="Lote de posições GPS dos agentes")
async def ingest_agents(
    payload: AgentPositionBatchInput, service: TelemetryServiceDep
) -> IngestOutput:
    result = await service.ingest_agent_positions(
        [
            AgentPositionReport(p.agent_id, p.recorded_at, GeoPoint(p.latitude, p.longitude))
            for p in payload.positions
        ]
    )
    return IngestOutput(accepted=result.accepted, unknown=result.unknown, arrivals=result.arrivals)
