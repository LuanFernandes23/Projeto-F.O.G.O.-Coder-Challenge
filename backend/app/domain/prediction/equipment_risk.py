"""Chance de cada equipamento falhar nas próximas 72 h (manutenção preditiva estatística).

taxa diária do equipamento = taxa do tipo (encolhida para a média do grupo)
                             × tendência recente do tipo (últimos 90 dias ÷ antes)
                             × fator da região (do modelo de risco)
                             × fator "preventiva vencida" (se estiver vencida agora)
                             × perfil das próximas 72 h (hora, dia, eventos; do modelo de risco)
P(falhar em 72 h) = 1 − exp(−taxa × 3 dias)

Cada fator é medido no histórico (e mostrado na tela): se o dado não sustentar um efeito,
o fator fica perto de 1 e a explicação diz isso.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from app.domain.prediction.risk_model import group_of

# Peso do impacto de uma falha por tipo (segurança viária e vigilância pesam mais).
IMPACT_WEIGHT = {"semaforo": 3.0, "radar": 2.0, "camera": 2.0, "viatura": 2.0, "moto_agente": 1.5}
SHRINK_DEVICE_DAYS = 400.0  # força do prior da taxa por tipo (em equipamento-dias)
SHRINK_EVENTS = 6.0
RECENT_DAYS = 90
HORIZON_DAYS = 3.0


@dataclass(frozen=True, slots=True)
class DeviceHistory:
    type_code: str
    installed_on: date
    failures: tuple[datetime, ...]  # horário local
    preventive_done: tuple[date, ...]  # conclusões de preventivas, em ordem
    plan_interval_days: int | None


@dataclass(frozen=True, slots=True)
class EquipmentRiskModel:
    type_rate: dict[str, float]  # falhas por equipamento-dia
    type_trend: dict[str, float]  # taxa recente ÷ taxa anterior (encolhida para 1)
    overdue_factor: float
    overdue_evidence: dict[str, float] = field(default_factory=dict)

    def as_params(self) -> dict[str, Any]:
        return {
            "type_rate_per_day": {k: round(v, 6) for k, v in self.type_rate.items()},
            "type_trend": {k: round(v, 3) for k, v in self.type_trend.items()},
            "overdue_factor": round(self.overdue_factor, 3),
            "overdue_evidence": self.overdue_evidence,
        }

    @classmethod
    def from_params(cls, params: dict[str, Any]) -> EquipmentRiskModel:
        return cls(
            dict(params["type_rate_per_day"]),
            dict(params["type_trend"]),
            float(params["overdue_factor"]),
            dict(params.get("overdue_evidence", {})),
        )


def _overdue_periods(history: DeviceHistory, until: date) -> list[tuple[date, date]]:
    """Períodos em que a preventiva estava vencida (prazo passou sem nova conclusão)."""
    if not history.plan_interval_days:
        return []
    periods: list[tuple[date, date]] = []
    anchor = history.installed_on
    for done in (*history.preventive_done, None):
        due = anchor + timedelta(days=history.plan_interval_days)
        end = done or until
        if end > due:
            periods.append((due, min(end, until)))
        if done is None:
            break
        anchor = done
    return periods


def fit_equipment_risk(histories: Sequence[DeviceHistory], today: date) -> EquipmentRiskModel:
    exposure: dict[str, float] = defaultdict(float)
    failures: dict[str, int] = defaultdict(int)
    recent_exposure: dict[str, float] = defaultdict(float)
    recent_failures: dict[str, int] = defaultdict(int)
    overdue_days: float = 0.0
    normal_days: float = 0.0
    overdue_failures = normal_failures = 0
    recent_start = today - timedelta(days=RECENT_DAYS)

    for h in histories:
        days = max((today - h.installed_on).days, 0)
        exposure[h.type_code] += days
        failures[h.type_code] += len(h.failures)
        recent_from = max(h.installed_on, recent_start)
        recent_exposure[h.type_code] += max((today - recent_from).days, 0)
        recent_failures[h.type_code] += sum(1 for f in h.failures if f.date() >= recent_start)
        periods = _overdue_periods(h, today)
        od = float(sum((end - start).days for start, end in periods))
        overdue_days += od
        normal_days += max(days - od, 0)
        hits = sum(1 for f in h.failures if any(s <= f.date() < e for s, e in periods))
        overdue_failures += hits
        normal_failures += len(h.failures) - hits

    group_exposure: dict[str, float] = defaultdict(float)
    group_failures: dict[str, int] = defaultdict(int)
    for type_code, device_days in exposure.items():
        group_exposure[group_of(type_code)] += device_days
        group_failures[group_of(type_code)] += failures[type_code]

    type_rate: dict[str, float] = {}
    type_trend: dict[str, float] = {}
    for type_code, device_days in exposure.items():
        group = group_of(type_code)
        prior = group_failures[group] / max(group_exposure[group], 1.0)
        rate = (failures[type_code] + prior * SHRINK_DEVICE_DAYS) / (
            device_days + SHRINK_DEVICE_DAYS
        )
        type_rate[type_code] = rate
        old_exposure = device_days - recent_exposure[type_code]
        old_failures = failures[type_code] - recent_failures[type_code]
        if old_exposure <= 0 or recent_exposure[type_code] <= 0:
            type_trend[type_code] = 1.0
            continue
        old_rate = (old_failures + rate * 50) / (old_exposure + 50)
        expected_recent = old_rate * recent_exposure[type_code]
        type_trend[type_code] = (recent_failures[type_code] + SHRINK_EVENTS) / (
            expected_recent + SHRINK_EVENTS
        )

    normal_rate = normal_failures / max(normal_days, 1.0)
    expected_overdue = normal_rate * overdue_days
    overdue_factor = (overdue_failures + SHRINK_EVENTS) / (expected_overdue + SHRINK_EVENTS)
    return EquipmentRiskModel(
        type_rate,
        type_trend,
        overdue_factor,
        {
            "overdue_device_days": round(overdue_days, 1),
            "overdue_failures": overdue_failures,
            "expected_if_no_effect": round(expected_overdue, 1),
        },
    )


@dataclass(frozen=True, slots=True)
class DeviceNow:
    equipment_id: str
    serial_number: str
    type_code: str
    type_name: str
    region: str | None
    neighborhood: str
    overdue: bool
    region_factor: float  # do modelo de risco
    horizon_profile: float  # perfil médio das próximas 72 h (do modelo de risco)


def score_devices(model: EquipmentRiskModel, devices: Sequence[DeviceNow]) -> list[dict[str, Any]]:
    """Probabilidade de falha em 72 h por equipamento, com os fatores que a explicam."""
    default_rate = sum(model.type_rate.values()) / max(len(model.type_rate), 1)
    results: list[dict[str, Any]] = []
    for d in devices:
        rate = model.type_rate.get(d.type_code, default_rate)
        trend = model.type_trend.get(d.type_code, 1.0)
        overdue = model.overdue_factor if d.overdue else 1.0
        daily = rate * trend * d.region_factor * overdue * d.horizon_profile
        probability = 1.0 - math.exp(-daily * HORIZON_DAYS)
        factors: list[dict[str, Any]] = [
            {"factor": f"Tipo ({d.type_name})", "multiplier": round(rate / default_rate, 2)},
            {"factor": "Tendência recente do tipo", "multiplier": round(trend, 2)},
            {"factor": f"Região {d.region or '—'}", "multiplier": round(d.region_factor, 2)},
            {
                "factor": "Próximas 72 h (horário, dia, eventos)",
                "multiplier": round(d.horizon_profile, 2),
            },
        ]
        if d.overdue:
            factors.append({"factor": "Preventiva vencida", "multiplier": round(overdue, 2)})
        factors.sort(key=lambda f: abs(math.log(max(float(f["multiplier"]), 1e-6))), reverse=True)
        results.append(
            {
                "equipment_id": d.equipment_id,
                "serial_number": d.serial_number,
                "type_code": d.type_code,
                "type_name": d.type_name,
                "region": d.region,
                "neighborhood": d.neighborhood,
                "overdue": d.overdue,
                "probability_72h": round(probability, 4),
                "impact": IMPACT_WEIGHT.get(d.type_code, 1.0),
                "priority": round(probability * IMPACT_WEIGHT.get(d.type_code, 1.0), 4),
                "factors": factors,
            }
        )
    results.sort(key=lambda r: r["probability_72h"], reverse=True)
    return results


def diversified(results: list[dict[str, Any]], per_type: int, limit: int) -> list[dict[str, Any]]:
    """Os mais prováveis, sem deixar um tipo muito frequente (ex.: patinete) tomar a lista."""
    counts: dict[str, int] = defaultdict(int)
    chosen: list[dict[str, Any]] = []
    for item in results:
        if counts[item["type_code"]] >= per_type:
            continue
        counts[item["type_code"]] += 1
        chosen.append(item)
        if len(chosen) >= limit:
            break
    return chosen
