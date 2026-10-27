"""Regras puras da Central: criticidade/SLA, saúde das regiões, despacho e telemetria."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.core.exceptions import BusinessRuleError, ConflictError, InvalidStatusTransitionError
from app.domain.agents.entities import AgentRole, DutyStatus
from app.domain.operations.alerts import (
    Alert,
    AlertKind,
    AlertSeverity,
    AlertStatus,
    dedup_key,
    ensure_can_acknowledge,
    failure_severity,
    offline_severity,
    overdue_severity,
    sla_due_at,
    sla_state,
    theft_severity,
)
from app.domain.operations.dispatch import (
    DispatchCandidate,
    DispatchStatus,
    eligible_roles,
    ensure_agent_dispatchable,
    ensure_dispatch_transition,
    estimate_eta_minutes,
    rank_suggestions,
)
from app.domain.operations.region_health import (
    HealthLevel,
    RegionMetrics,
    classify,
    compute_region_health,
)
from app.domain.operations.telemetry import (
    Connectivity,
    battery_alert_change,
    connectivity,
    distance_m,
    should_sample,
)
from app.domain.shared import GeoPoint

NOW = datetime(2026, 10, 26, 14, 0, tzinfo=UTC)


class TestSeverity:
    @pytest.mark.parametrize(
        ("type_code", "region", "expected"),
        [
            ("semaforo", "norte", AlertSeverity.CRITICA),
            ("semaforo", "centro", AlertSeverity.CRITICA),
            ("camera", "norte", AlertSeverity.ALTA),
            ("camera", "centro", AlertSeverity.CRITICA),  # +1 nível no Centro
            ("totem_estacionamento", "sul", AlertSeverity.MEDIA),
            ("patinete", "leste", AlertSeverity.BAIXA),
            ("patinete", "centro", AlertSeverity.MEDIA),
            ("desconhecido", None, AlertSeverity.BAIXA),
        ],
    )
    def test_failure_severity(
        self, type_code: str, region: str | None, expected: AlertSeverity
    ) -> None:
        assert failure_severity(type_code, region) is expected

    def test_theft_of_vehicles_and_cameras_is_critical(self) -> None:
        assert theft_severity("viatura") is AlertSeverity.CRITICA
        assert theft_severity("patinete") is AlertSeverity.ALTA

    def test_offline_is_one_level_below_failure_but_never_below_low(self) -> None:
        assert offline_severity("semaforo", "norte") is AlertSeverity.ALTA
        assert offline_severity("patinete", "norte") is AlertSeverity.BAIXA

    def test_overdue_maintenance_of_critical_equipment_is_medium(self) -> None:
        assert overdue_severity("radar") is AlertSeverity.MEDIA
        assert overdue_severity("patinete") is AlertSeverity.BAIXA


class TestSla:
    def _alert(self, severity: AlertSeverity, status: AlertStatus = AlertStatus.ABERTO) -> Alert:
        return Alert(
            id=uuid4(),
            kind=AlertKind.FALHA_EQUIPAMENTO,
            severity=severity,
            status=status,
            title="t",
            description="d",
            dedup_key="k",
            opened_at=NOW,
            sla_due_at=sla_due_at(severity, NOW),
            last_occurrence_at=NOW,
        )

    @pytest.mark.parametrize(
        ("severity", "hours"),
        [
            (AlertSeverity.CRITICA, 1),
            (AlertSeverity.ALTA, 4),
            (AlertSeverity.MEDIA, 24),
            (AlertSeverity.BAIXA, 72),
        ],
    )
    def test_sla_by_severity(self, severity: AlertSeverity, hours: int) -> None:
        assert sla_due_at(severity, NOW) == NOW + timedelta(hours=hours)

    def test_sla_breach_is_computed_at_read_time(self) -> None:
        alert = self._alert(AlertSeverity.CRITICA)
        assert not sla_state(alert, NOW + timedelta(minutes=59)).breached
        late = sla_state(alert, NOW + timedelta(minutes=61))
        assert late.breached
        assert late.remaining_seconds == -60

    def test_resolved_alert_sla_is_frozen_at_resolution(self) -> None:
        alert = self._alert(AlertSeverity.CRITICA, AlertStatus.RESOLVIDO)
        alert.resolved_at = NOW + timedelta(minutes=30)
        assert not sla_state(alert, NOW + timedelta(days=3)).breached

    def test_only_open_alerts_can_be_acknowledged(self) -> None:
        with pytest.raises(ConflictError):
            ensure_can_acknowledge(self._alert(AlertSeverity.ALTA, AlertStatus.RECONHECIDO))

    def test_dedup_key_is_stable_per_kind_and_subject(self) -> None:
        subject = uuid4()
        assert dedup_key(AlertKind.FURTO, subject) == f"furto:{subject}"


def _metrics(**overrides: object) -> RegionMetrics:
    data: dict[str, object] = {
        "region_id": uuid4(),
        "code": "centro",
        "name": "Centro",
        "operational": 100,
        "unavailable": 0,
        "offline": 0,
        "immediate_maintenance": 0,
        "overdue_maintenance": 0,
        "agents_on_duty": 5,
        "open_alerts": {},
    }
    data.update(overrides)
    return RegionMetrics(**data)  # type: ignore[arg-type]


class TestRegionHealth:
    def test_perfect_region_is_normal(self) -> None:
        health = compute_region_health(_metrics())
        assert (health.score, health.level) == (100.0, HealthLevel.NORMAL)
        assert health.reasons == ("Sem ocorrências relevantes",)

    def test_critical_alerts_and_outages_degrade_the_region(self) -> None:
        health = compute_region_health(
            _metrics(
                operational=80,
                unavailable=20,
                offline=10,
                immediate_maintenance=8,
                open_alerts={AlertSeverity.CRITICA: 2, AlertSeverity.ALTA: 1},
            )
        )
        assert health.level is HealthLevel.CRITICO
        assert health.availability_pct == 80.0
        assert any("crítico" in reason for reason in health.reasons)

    def test_acknowledged_alerts_weigh_half(self) -> None:
        unhandled = compute_region_health(_metrics(open_alerts={AlertSeverity.ALTA: 2}))
        handled = compute_region_health(_metrics(acknowledged_alerts={AlertSeverity.ALTA: 2}))
        assert (unhandled.score, handled.score) == (92.0, 98.0)

    def test_alert_penalty_is_capped(self) -> None:
        health = compute_region_health(_metrics(open_alerts={AlertSeverity.CRITICA: 50}))
        assert health.score == 60.0

    def test_empty_region_does_not_divide_by_zero(self) -> None:
        assert compute_region_health(_metrics(operational=0)).score == 100.0

    @pytest.mark.parametrize(
        ("score", "level"),
        [
            (85, HealthLevel.NORMAL),
            (84.9, HealthLevel.ATENCAO),
            (70, HealthLevel.ATENCAO),
            (69.9, HealthLevel.CRITICO),
        ],
    )
    def test_thresholds(self, score: float, level: HealthLevel) -> None:
        assert classify(score) is level


class TestDispatch:
    def test_theft_requires_security_forces(self) -> None:
        assert eligible_roles(AlertKind.FURTO, "camera") == (
            AgentRole.GUARDA_MUNICIPAL,
            AgentRole.POLICIAL_MILITAR,
        )

    def test_traffic_equipment_prefers_traffic_agents(self) -> None:
        assert (
            eligible_roles(AlertKind.FALHA_EQUIPAMENTO, "semaforo")[0] is AgentRole.AGENTE_TRANSITO
        )

    def test_eta_uses_detour_factor_and_vehicle_speed(self) -> None:
        # 3 km * 1,3 a 35 km/h ≈ 6,7 min; a pé (5 km/h) ≈ 46,8 min
        assert estimate_eta_minutes(3000, "viatura") == pytest.approx(6.7, abs=0.1)
        assert estimate_eta_minutes(3000, None) == pytest.approx(46.8, abs=0.1)

    def test_lifecycle_transitions(self) -> None:
        ensure_dispatch_transition(DispatchStatus.DESIGNADO, DispatchStatus.A_CAMINHO)
        ensure_dispatch_transition(DispatchStatus.NO_LOCAL, DispatchStatus.CONCLUIDO)
        with pytest.raises(InvalidStatusTransitionError):
            ensure_dispatch_transition(DispatchStatus.CONCLUIDO, DispatchStatus.NO_LOCAL)

    def test_busy_or_off_duty_agent_cannot_be_dispatched(self) -> None:
        roles = (AgentRole.GUARDA_MUNICIPAL,)
        ensure_agent_dispatchable(True, DutyStatus.EM_PATRULHA, AgentRole.GUARDA_MUNICIPAL, roles)
        with pytest.raises(BusinessRuleError):
            ensure_agent_dispatchable(
                True, DutyStatus.EM_OCORRENCIA, AgentRole.GUARDA_MUNICIPAL, roles
            )
        with pytest.raises(BusinessRuleError):
            ensure_agent_dispatchable(True, DutyStatus.DISPONIVEL, AgentRole.AGENTE_TRANSITO, roles)

    def test_suggestions_are_ranked_by_eta_not_by_raw_distance(self) -> None:
        def candidate(name: str, distance: float, vehicle: str | None) -> DispatchCandidate:
            return DispatchCandidate(
                uuid4(),
                name,
                AgentRole.GUARDA_MUNICIPAL,
                "GCM",
                DutyStatus.DISPONIVEL,
                GeoPoint(-22.2, -49.9),
                distance,
                vehicle,
            )

        walking_near = candidate("a pé", 800, None)  # ~12,5 min
        car_far = candidate("viatura", 2500, "viatura")  # ~5,6 min
        ranked = rank_suggestions([walking_near, car_far], (AgentRole.GUARDA_MUNICIPAL,), 5)
        assert [s.candidate.full_name for s in ranked] == ["viatura", "a pé"]


class TestTelemetry:
    def test_connectivity_states(self) -> None:
        assert connectivity(None, NOW) is Connectivity.SEM_TELEMETRIA
        assert connectivity(NOW - timedelta(minutes=4), NOW) is Connectivity.ONLINE
        assert connectivity(NOW - timedelta(minutes=6), NOW) is Connectivity.OFFLINE

    @pytest.mark.parametrize(
        ("previous", "current", "expected"),
        [
            (50.0, 12.0, True),  # caiu abaixo do limite: abre alerta
            (12.0, 20.0, None),  # dentro da histerese: nada muda
            (12.0, 30.0, False),  # recuperou: resolve
            (90.0, 85.0, None),
            (None, None, None),
        ],
    )
    def test_battery_hysteresis(
        self, previous: float | None, current: float | None, expected: bool | None
    ) -> None:
        assert battery_alert_change(previous, current) is expected

    def test_sampling_interval(self) -> None:
        assert should_sample(None, NOW, timedelta(minutes=5))
        assert not should_sample(NOW - timedelta(minutes=4), NOW, timedelta(minutes=5))
        assert should_sample(NOW - timedelta(minutes=5), NOW, timedelta(minutes=5))

    def test_haversine_distance(self) -> None:
        # 0,001 grau de latitude ≈ 111 m
        assert distance_m(GeoPoint(-22.2, -49.9), GeoPoint(-22.201, -49.9)) == pytest.approx(
            111.2, abs=0.5
        )
