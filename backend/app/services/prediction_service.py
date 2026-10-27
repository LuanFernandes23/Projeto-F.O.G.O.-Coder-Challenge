"""Cidade Preditiva: ajusta os modelos, gera as previsões e vigia anomalias ao vivo.

Fluxo:
- ``fit_models`` (diário e ao subir): ajusta o modelo de risco e o de equipamentos com o
  histórico, faz o backtest (treina sem as últimas 8 semanas e prevê essas semanas) e grava
  tudo em ``prediction_models`` (auditável).
- ``refresh`` (a cada 5 min): usa o último modelo para prever os próximos 7 dias e grava o
  retrato em ``prediction_snapshots`` (o front só lê, não recalcula).
- ``scan_anomalies`` (a cada minuto): procura precursores de falha na telemetria e picos
  regionais, abre alertas preventivos e mede ao vivo a precisão e a antecedência.
"""

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import numpy as np

from app.core.clock import Clock
from app.domain.operations.alerts import AlertKind, AlertSeverity, anomaly_severity
from app.domain.operations.events import DomainEvent, EventType
from app.domain.prediction.anomaly import median_mad, regional_surprise, score_device
from app.domain.prediction.backtest import Calibration, evaluate
from app.domain.prediction.equipment_risk import (
    DeviceNow,
    EquipmentRiskModel,
    diversified,
    fit_equipment_risk,
    score_devices,
)
from app.domain.prediction.precursor_model import MIN_LABELS, PrecursorModel, train
from app.domain.prediction.reinforcement import RegionWindow, recommend
from app.domain.prediction.risk_model import (
    BLOCK_HOURS,
    EVENT_KINDS,
    GROUPS,
    Installation,
    RiskModel,
    build_grid,
    day_type,
    expected_cube,
    fit,
    group_of,
)
from app.domain.prediction.trends import project
from app.services.alert_engine import AlertEngine
from app.services.ports import UnitOfWork

logger = logging.getLogger(__name__)

MODEL_KIND = "risco_cidade"
PRECURSOR_MODEL_KIND = "classificador_precursores"
PRECURSOR_TRAINING_LIMIT = 2_000
SNAPSHOT_CITY = "cidade"
SNAPSHOT_ANOMALIES = "anomalias"
PREDICTION_LOCK_KEY = 7_412_031
ANOMALY_LOCK_KEY = 7_412_032
HISTORY_DAYS = 365
BACKTEST_DAYS = 56
HORIZON_HOURS = 24 * 7
DETECTION_TTL = timedelta(minutes=30)  # precursor sem falha nesse prazo = alarme falso
SURPRISE_WINDOW = timedelta(hours=3)
AVAILABILITY_TARGET = 90.0
MIN_CASES = 10


def risk_level(ratio: float) -> str:
    if ratio >= 2.0:
        return "muito_alto"
    if ratio >= 1.3:
        return "alto"
    if ratio >= 0.8:
        return "moderado"
    return "baixo"


class PredictionService:
    def __init__(
        self, uow: UnitOfWork, clock: Clock, tz: ZoneInfo, engine: AlertEngine | None = None
    ) -> None:
        self._uow = uow
        self._clock = clock
        self._zone = tz
        self._engine = engine or AlertEngine()

    @property
    def _tz(self) -> str:
        return self._zone.key

    def _local_now(self) -> datetime:
        return self._clock.now().astimezone(self._zone).replace(tzinfo=None)

    # ---- ajuste + backtest --------------------------------------------------------------------

    async def fit_models(self) -> dict[str, Any]:
        now = self._clock.now()
        today = self._local_now().date()
        start = today - timedelta(days=HISTORY_DAYS)
        async with self._uow as uow:
            if not await uow.job_locks.try_acquire(PREDICTION_LOCK_KEY):
                return {"skipped": True}
            regions = [code for _, code, _ in await uow.predictions.region_codes()]
            installations = await uow.predictions.installations(self._tz)
            since = datetime.combine(start, datetime.min.time(), tzinfo=self._zone)
            operating = await uow.predictions.operational_exposure(self._tz, since)
            occurrences = await uow.predictions.occurrences(self._tz, since)
            calendar = await uow.predictions.calendar(self._tz, since, now + timedelta(days=30))
            histories = await uow.predictions.device_histories(self._tz)

            split = today - timedelta(days=BACKTEST_DAYS)
            train = build_grid(
                regions, start, split, installations, occurrences, calendar, operating=operating
            )
            test = build_grid(
                regions, split, today, installations, occurrences, calendar, operating=operating
            )
            backtest = evaluate(fit(train), train, test)

            full = build_grid(
                regions, start, today, installations, occurrences, calendar, operating=operating
            )
            model = fit(full)
            equipment = fit_equipment_risk(histories, today)
            model_id = await uow.predictions.save_model(
                MODEL_KIND,
                now,
                since,
                now,
                {"risk": model.as_params(), "equipment": equipment.as_params()},
                {"backtest": backtest, "equipment": equipment.overdue_evidence},
            )
            await uow.commit()
        logger.info(
            "Modelos preditivos ajustados",
            extra={
                "model_id": model_id,
                "events": model.observed_events,
                "skill_vs_mean": backtest["skill_vs_mean"],
                "top20_capture": backtest["top20_capture"],
            },
        )
        return {"model_id": model_id, "backtest": backtest}

    async def _latest(self) -> tuple[int, RiskModel, EquipmentRiskModel, dict[str, Any]] | None:
        async with self._uow as uow:
            run = await uow.predictions.latest_model(MODEL_KIND)
        if run is None:
            return None
        return (
            run.id,
            RiskModel.from_params(run.params["risk"]),
            EquipmentRiskModel.from_params(run.params["equipment"]),
            {**run.metrics, "fitted_at": run.fitted_at.isoformat()},
        )

    async def calibration(self) -> Calibration | None:
        latest = await self._latest()
        if latest is None:
            return None
        return Calibration.from_dict(latest[3]["backtest"]["calibration"])

    # ---- previsão (snapshot) -----------------------------------------------------------------

    async def refresh(self) -> dict[str, Any]:
        latest = await self._latest()
        if latest is None:
            await self.fit_models()
            latest = await self._latest()
            if latest is None:
                return {}
        model_id, model, equipment_model, metrics = latest
        now_local = self._local_now().replace(minute=0, second=0, microsecond=0)
        today = now_local.date()
        now = self._clock.now()
        async with self._uow as uow:
            regions = await uow.predictions.region_codes()
            calendar = await uow.predictions.calendar(self._tz, now, now + timedelta(days=8))
            events = await uow.predictions.event_public(self._tz, now, now + timedelta(days=8))
            devices = await uow.predictions.devices_now(today)
            availability = await uow.predictions.availability_by_type(60)
            on_duty = await uow.predictions.on_duty_by_region()
            handling = await uow.predictions.handling_minutes_by_region(90)
            averted = await uow.predictions.averted_counts(now - timedelta(days=7))

        region_codes = [code for _, code, _ in regions]
        # Previsão: exposição = equipamentos operacionais agora, mantidos no horizonte.
        installations = [
            Installation(d["region"], d["type_code"], today) for d in devices if d["region"]
        ]
        names = {code: name for _, code, name in regions}
        grid = build_grid(
            region_codes,
            today,
            today + timedelta(days=9),
            installations,
            [],
            calendar,
            fixed_exposure=True,
        )
        lam = expected_cube(model, grid)  # [R, G, D, H]
        by_region = lam.sum(axis=1)  # [R, D, H]
        offset = now_local.hour
        flat = by_region.reshape(len(region_codes), -1)[:, offset : offset + HORIZON_HOURS]
        mean_cell = float(flat.mean()) or 1e-9
        hours = [now_local + timedelta(hours=i) for i in range(HORIZON_HOURS)]

        cells = []
        for r, code in enumerate(region_codes):
            for i, when in enumerate(hours):
                expected = float(flat[r, i])
                ratio = expected / mean_cell
                cells.append(
                    {
                        "region": code,
                        "at": when.isoformat(),
                        "expected": round(expected, 4),
                        "probability": round(1 - float(np.exp(-expected)), 4),
                        "index": min(100, round(50 * ratio)),
                        "level": risk_level(ratio),
                    }
                )

        explain = {}
        for r, code in enumerate(region_codes):
            for when in hours[:24]:
                d, h = (when.date() - today).days, when.hour
                group = int(np.argmax(lam[r, :, d, h]))
                explain[f"{code}|{when.isoformat()}"] = {
                    "group": GROUPS[group],
                    "factors": model.explain(r, group, when, int(grid.events[r, d, h])),
                }

        hotspots = self._hotspots(model, grid, by_region, region_codes, names, hours, events)
        equipment_risk = self._equipment_risk(
            model, equipment_model, grid, region_codes, devices, now_local
        )
        reinforcement = self._reinforcement(
            by_region, region_codes, names, now_local, today, on_duty, events, handling
        )
        trends = []
        for type_code, series in availability.items():
            projection = project(series, AVAILABILITY_TARGET)
            trends.append(
                {
                    "type_code": type_code,
                    "series": [{"date": d.isoformat(), "value": round(v, 2)} for d, v in series],
                    **projection,
                }
            )
        trends.sort(key=lambda t: t["slope_per_week"])

        payload = {
            "generated_at": now.isoformat(),
            "model": {
                "id": model_id,
                "fitted_at": metrics["fitted_at"],
                "observed_events": model.observed_events,
                "excluded_days": model.excluded_days,
                "factors": self._factor_summary(model, region_codes, names),
                "equipment": equipment_model.as_params(),
            },
            "backtest": metrics["backtest"],
            "regions": [{"code": c, "name": names[c]} for c in region_codes],
            "cells": cells,
            "explain": explain,
            "hotspots": hotspots,
            "equipment_risk": diversified(equipment_risk, per_type=3, limit=30),
            "equipment_priority": sorted(equipment_risk, key=lambda r: r["priority"], reverse=True)[
                :10
            ],
            "reinforcement": reinforcement,
            "trends": trends,
            "events": [
                {**e, "starts_at": e["starts_at"].isoformat(), "ends_at": e["ends_at"].isoformat()}
                for e in events
                if e["starts_at"] < now_local + timedelta(days=7)
            ],
            "averted_last_7_days": averted,
        }
        async with self._uow as uow:
            await uow.predictions.save_snapshot(SNAPSHOT_CITY, now, payload, model_id)
            await uow.events.publish(
                DomainEvent(EventType.PREDICTION_UPDATED, {"kind": SNAPSHOT_CITY})
            )
            await uow.commit()
        return payload

    @staticmethod
    def _factor_summary(
        model: RiskModel, regions: list[str], names: dict[str, str]
    ) -> dict[str, Any]:
        return {
            "region": [
                {"region": code, "name": names[code], "multiplier": round(float(v), 2)}
                for code, v in zip(regions, model.region, strict=True)
            ],
            "hour": [round(float(v), 2) for v in model.hour],
            "week": {
                group: [[round(float(x), 2) for x in row] for row in model.week[g]]
                for g, group in enumerate(GROUPS)
            },
            "month": {
                group: [round(float(x), 2) for x in model.month[g]]
                for g, group in enumerate(GROUPS)
            },
            "event": {
                group: {
                    kind: round(float(model.event[g, k]), 2)
                    for k, kind in enumerate(EVENT_KINDS)
                    if k
                }
                for g, group in enumerate(GROUPS)
            },
        }

    @staticmethod
    def _hotspots(
        model: RiskModel,
        grid: Any,
        by_region: Any,
        regions: list[str],
        names: dict[str, str],
        hours: list[datetime],
        events: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        today = hours[0].date()
        windows: list[dict[str, Any]] = []
        for r, code in enumerate(regions):
            for start in range(0, len(hours) - BLOCK_HOURS + 1, BLOCK_HOURS):
                block = hours[start : start + BLOCK_HOURS]
                values = [by_region[r, (h.date() - today).days, h.hour] for h in block]
                peak = block[int(np.argmax(values))]
                d = (peak.date() - today).days
                windows.append(
                    {
                        "region": code,
                        "region_name": names[code],
                        "starts_at": block[0].isoformat(),
                        "ends_at": (block[-1] + timedelta(hours=1)).isoformat(),
                        "expected": round(float(sum(values)), 3),
                        "peak_at": peak.isoformat(),
                        "factors": model.explain(
                            r,
                            int(np.argmax(grid_lambda_groups(model, grid, r, d, peak.hour))),
                            peak,
                            int(grid.events[r, d, peak.hour]),
                        ),
                        "events": [
                            e["name"]
                            for e in events
                            if e["region"] in (None, code)
                            and e["starts_at"] < block[-1] + timedelta(hours=1)
                            and e["ends_at"] > block[0]
                        ],
                    }
                )
        mean = sum(w["expected"] for w in windows) / max(len(windows), 1)
        for w in windows:
            w["ratio"] = round(w["expected"] / mean, 2) if mean else 1.0
        windows.sort(key=lambda w: w["expected"], reverse=True)
        chosen: list[dict[str, Any]] = []
        per_region: dict[str, int] = defaultdict(int)
        for w in windows:  # no máximo 2 janelas por região: a semana inteira, não só o Centro
            if per_region[w["region"]] < 2:
                per_region[w["region"]] += 1
                chosen.append(w)
            if len(chosen) == 8:
                break
        return chosen

    @staticmethod
    def _equipment_risk(
        model: RiskModel,
        equipment_model: EquipmentRiskModel,
        grid: Any,
        regions: list[str],
        devices: list[dict[str, Any]],
        now_local: datetime,
    ) -> list[dict[str, Any]]:
        today = now_local.date()
        r_index = {code: i for i, code in enumerate(regions)}
        profile: dict[tuple[int, int], float] = {}
        horizon = [now_local + timedelta(hours=i) for i in range(72)]
        for r in range(len(regions)):
            for g in range(len(GROUPS)):
                values = []
                for when in horizon:
                    d = (when.date() - today).days
                    values.append(
                        model.hour[when.hour]
                        * model.week[g, day_type(when.weekday()), when.hour // BLOCK_HOURS]
                        * model.month[g, when.month - 1]
                        * model.event[g, grid.events[r, d, when.hour]]
                    )
                profile[(r, g)] = float(np.mean(values))
        now_devices = []
        for device in devices:
            idx = r_index.get(device["region"]) if device["region"] else None
            group = GROUPS.index(group_of(device["type_code"]))
            now_devices.append(
                DeviceNow(
                    equipment_id=str(device["id"]),
                    serial_number=device["serial_number"],
                    type_code=device["type_code"],
                    type_name=device["type_name"],
                    region=device["region"],
                    neighborhood=device["neighborhood"],
                    overdue=bool(device["overdue"]),
                    region_factor=float(model.region[idx]) if idx is not None else 1.0,
                    horizon_profile=profile.get((idx, group), 1.0) if idx is not None else 1.0,
                )
            )
        return score_devices(equipment_model, now_devices)

    @staticmethod
    def _reinforcement(
        by_region: Any,
        regions: list[str],
        names: dict[str, str],
        now_local: datetime,
        today: date,
        on_duty: dict[str, int],
        events: list[dict[str, Any]],
        handling: dict[str, float],
    ) -> list[dict[str, Any]]:
        blocks = []
        first = now_local.replace(hour=now_local.hour - now_local.hour % BLOCK_HOURS)
        for b in range(3):
            start = first + timedelta(hours=BLOCK_HOURS * b)
            end = start + timedelta(hours=BLOCK_HOURS)
            windows = []
            for r, code in enumerate(regions):
                expected = 0.0
                for h in range(BLOCK_HOURS):
                    moment = start + timedelta(hours=h)
                    d = (moment.date() - today).days
                    expected += float(by_region[r, d, moment.hour])
                overlapping = [
                    e
                    for e in events
                    if e["region"] in (None, code) and e["starts_at"] < end and e["ends_at"] > start
                ]
                windows.append(
                    RegionWindow(
                        code,
                        expected,
                        on_duty.get(code, 0),
                        sum(int(e["expected_public"]) for e in overlapping),
                        tuple(e["name"] for e in overlapping),
                    )
                )
            result = recommend(windows)
            for row in result["regions"]:
                row["region_name"] = names[row["region"]]
                row["handling_minutes"] = handling.get(row["region"])
            blocks.append({"starts_at": start.isoformat(), "ends_at": end.isoformat(), **result})
        return blocks

    # ---- anomalias ao vivo -------------------------------------------------------------------

    async def scan_anomalies(self) -> dict[str, Any]:
        now = self._clock.now()
        opened = expired = 0
        async with self._uow as uow:
            if not await uow.job_locks.try_acquire(ANOMALY_LOCK_KEY):
                return {"skipped": True}
            window = await uow.predictions.telemetry_window(
                now - timedelta(minutes=60), now - timedelta(minutes=2)
            )
            open_detections = await uow.predictions.open_detections()
            classifier_run = await uow.predictions.latest_model(PRECURSOR_MODEL_KIND)
            classifier = (
                PrecursorModel.from_params(classifier_run.params, classifier_run.metrics)
                if classifier_run
                else None
            )
            findings: list[dict[str, Any]] = []
            for equipment_id, data in window.items():
                baselines = {}
                for metric in ("temperature_c", "signal_dbm", "uptime_pct"):
                    values = [
                        float(r[metric])
                        for r in data["readings"]
                        if isinstance(r.get(metric), int | float)
                    ]
                    baselines[metric] = median_mad(values)
                result = score_device(data["current"], baselines)
                if not result.is_anomaly:
                    continue
                findings.append(
                    {
                        "equipment_id": str(equipment_id),
                        "serial_number": data["serial_number"],
                        "type_code": data["type_code"],
                        "region": data["region"],
                        "neighborhood": data["neighborhood"],
                        "score": result.score,
                        "signals": result.signals,
                        "z": result.z,
                        "p_real": (
                            round(classifier.probability(result.z, data["type_code"]), 3)
                            if classifier
                            else None
                        ),
                    }
                )
                if equipment_id in open_detections:
                    continue
                await uow.predictions.add_detection(
                    equipment_id, now, result.score, {"signals": result.signals, "z": result.z}
                )
                opened += 1
                type_name = await self._engine.type_name(uow, data["type_code"])
                await self._engine.raise_alert(
                    uow,
                    kind=AlertKind.ANOMALIA_DETECTADA,
                    subject_id=equipment_id,
                    severity=anomaly_severity(data["type_code"], data["region"]),
                    title=f"{type_name} {data['serial_number']}: sinais de falha iminente",
                    description="; ".join(
                        f"{s['label']} {s['value']} (normal ≈ {s['baseline']}, z = {s['z']})"
                        for s in result.signals
                    ),
                    now=now,
                    equipment_id=equipment_id,
                    region_id=data["region_id"],
                    metadata={"score": result.score, "signals": result.signals},
                )
                await uow.events.publish(
                    DomainEvent(
                        EventType.ANOMALY_DETECTED,
                        {"equipment_id": str(equipment_id), "score": result.score},
                    )
                )
            for equipment_id in await uow.predictions.expire_detections(now - DETECTION_TTL, now):
                expired += 1
                await self._engine.resolve(
                    uow,
                    AlertKind.ANOMALIA_DETECTADA,
                    equipment_id,
                    now=now,
                    note="Sinais normalizados sem falha em 30 min (alarme falso).",
                )
            regional = await self._regional(uow, now)
            quality = await uow.predictions.detection_quality(now - timedelta(hours=24))
            learning = await self._learn_precursors(uow, now, classifier)
            payload = {
                "generated_at": now.isoformat(),
                "devices": sorted(findings, key=lambda f: f["score"], reverse=True),
                "regional": regional,
                "quality": _quality(quality),
                "learning": learning,
            }
            await uow.predictions.save_snapshot(SNAPSHOT_ANOMALIES, now, payload, None)
            await uow.commit()
        return {"opened": opened, "expired": expired, "devices": len(payload["devices"])}

    async def _learn_precursors(
        self, uow: UnitOfWork, now: datetime, current: PrecursorModel | None
    ) -> dict[str, Any]:
        """Retreina o classificador quando chegam desfechos novos (aprendizado contínuo)."""
        samples = await uow.predictions.labeled_detections(PRECURSOR_TRAINING_LIMIT)
        model = current
        if samples and (current is None or len(samples) != current.trained_on):
            trained = train(samples)
            if trained is not None:
                await uow.predictions.save_model(
                    PRECURSOR_MODEL_KIND,
                    now,
                    min(s.detected_at for s in samples),
                    now,
                    trained.as_params(),
                    trained.metrics,
                )
                model = trained
        return {
            "active": model is not None,
            "labels": len(samples),
            "min_labels": MIN_LABELS,
            "metrics": model.metrics if model else {},
            "explain": model.explain() if model else [],
        }

    async def _regional(self, uow: UnitOfWork, now: datetime) -> list[dict[str, Any]]:
        run = await uow.predictions.latest_model(MODEL_KIND)
        if run is None:
            return []
        model = RiskModel.from_params(run.params["risk"])
        observed = await uow.predictions.live_occurrences_by_region(now - SURPRISE_WINDOW)
        local = self._local_now()
        weights: dict[str, float] = defaultdict(float)
        for r, code in enumerate(model.regions):
            for h in range(int(SURPRISE_WINDOW.total_seconds() // 3600)):
                moment = local - timedelta(hours=h)
                for g in range(len(GROUPS)):
                    weights[code] += model.rate(r, g, moment, 0, 1.0)
        total = sum(weights.values()) or 1.0
        share = {code: w / total for code, w in weights.items()}
        findings = regional_surprise(observed, share)
        regions = {code: (rid, name) for rid, code, name in await uow.predictions.region_codes()}
        for finding in findings:
            region_id, name = regions[finding["region"]]
            finding["region_name"] = name
            await self._engine.raise_alert(
                uow,
                kind=AlertKind.PREVISAO_RISCO,
                subject_id=region_id,
                severity=AlertSeverity.ALTA,
                title=f"{name}: ocorrências acima do padrão nas últimas 3 h",
                description=(
                    f"{finding['observed']} ocorrências, quando o esperado pela participação "
                    f"histórica seria {finding['expected']} (p = {finding['p_value']})."
                ),
                now=now,
                region_id=region_id,
                metadata=finding,
                count_occurrence=False,
            )
        return findings

    # ---- leitura -----------------------------------------------------------------------------

    async def snapshot(self, kind: str) -> dict[str, Any] | None:
        async with self._uow as uow:
            row = await uow.predictions.get_snapshot(kind)
        return dict(row.payload) if row else None


async def on_fault(uow: UnitOfWork, engine: AlertEngine, equipment_id: UUID, now: datetime) -> None:
    """Falha confirmada: se havia precursor aberto, a detecção acertou."""
    if await uow.predictions.close_detection(equipment_id, "falhou", now):
        await engine.resolve(
            uow,
            AlertKind.ANOMALIA_DETECTADA,
            equipment_id,
            now=now,
            note="Falha confirmada (o precursor foi detectado antes).",
        )


async def on_averted(
    uow: UnitOfWork, engine: AlertEngine, equipment_id: UUID, intervention: str, now: datetime
) -> None:
    """Falha iminente que não aconteceu: registra e credita a decisão que a evitou."""
    await uow.predictions.close_detection(equipment_id, "evitada", now)
    await uow.predictions.record_averted(equipment_id, now, intervention)
    await engine.resolve(
        uow,
        AlertKind.ANOMALIA_DETECTADA,
        equipment_id,
        now=now,
        note="Falha evitada: houve intervenção antes do defeito.",
    )
    await uow.events.publish(
        DomainEvent(
            EventType.FAULT_AVERTED,
            {"equipment_id": str(equipment_id), "intervention": intervention},
        )
    )


def grid_lambda_groups(model: RiskModel, grid: Any, r: int, d: int, hour: int) -> list[float]:
    when = datetime.combine(grid.days[d], datetime.min.time()).replace(hour=hour)
    return [
        model.rate(r, g, when, int(grid.events[r, d, hour]), float(grid.exposure[r, g, d]))
        for g in range(len(GROUPS))
    ]


def _quality(row: dict[str, Any]) -> dict[str, Any]:
    failed, averted = int(row["failed"] or 0), int(row["averted"] or 0)
    false_alarms = int(row["false_alarms"] or 0)
    decided = failed + averted + false_alarms
    live_failures = int(row["live_failures"] or 0)
    return {
        "detections_confirmed": failed,
        "detections_averted": averted,
        "false_alarms": false_alarms,
        "pending": int(row["pending"] or 0),
        "decided": decided,
        # Abaixo de 10 casos a porcentagem engana: a tela mostra "poucos casos".
        "precision": round((failed + averted) / decided, 3) if decided >= MIN_CASES else None,
        "recall": round(failed / live_failures, 3) if live_failures >= MIN_CASES else None,
        "mean_lead_minutes": round(float(row["lead"]), 1) if row["lead"] else None,
        "live_failures": live_failures,
    }
