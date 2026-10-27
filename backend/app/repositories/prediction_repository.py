"""Persistência e consultas do motor preditivo (Parte 3).

As consultas devolvem horários locais "sem fuso" (``AT TIME ZONE``), que é como o modelo
raciocina sobre hora do dia e dia da semana.
"""

import json
from collections import defaultdict
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models.intelligence import (
    AnomalyDetectionModel,
    AvertedFaultModel,
    PredictionModelRun,
    PredictionSnapshotModel,
)
from app.domain.prediction.equipment_risk import DeviceHistory
from app.domain.prediction.precursor_model import LabeledDetection
from app.domain.prediction.records import ModelRun, Snapshot
from app.domain.prediction.risk_model import EventWindow, Installation, Occurrence


class SqlPredictionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ---- dados de treino -----------------------------------------------------------------

    async def region_codes(self) -> list[tuple[UUID, str, str]]:
        rows = await self._session.execute(text("SELECT id, code, name FROM regions ORDER BY code"))
        return [(r.id, r.code, r.name) for r in rows]

    async def installations(self, tz: str) -> list[Installation]:
        rows = await self._session.execute(
            text(
                """
                SELECT r.code AS region, e.type_code,
                       (min(h.changed_at) AT TIME ZONE :tz)::date AS installed_on
                FROM equipment e
                JOIN regions r ON r.id = e.region_id
                JOIN equipment_status_history h
                  ON h.equipment_id = e.id AND h.to_status = 'operacional'
                WHERE e.archived_at IS NULL
                GROUP BY e.id, r.code, e.type_code
                """
            ),
            {"tz": tz},
        )
        return [Installation(r.region, r.type_code, r.installed_on) for r in rows]

    async def operational_exposure(
        self, tz: str, since: datetime
    ) -> list[tuple[str, str, date, float]]:
        """Equipamento-dias EM OPERAÇÃO por (região, tipo, dia local).

        Quem está em reparo não pode falhar: medir a exposição pelo tempo operacional (e não
        pelo parque instalado) evita confundir "região de mais falhas" com "reparo mais lento".
        """
        rows = await self._session.execute(
            text(
                """
                WITH intervals AS (
                    SELECT h.equipment_id, h.to_status,
                           (h.changed_at AT TIME ZONE :tz) AS starts,
                           (coalesce(lead(h.changed_at) OVER w, now()) AT TIME ZONE :tz) AS ends
                    FROM equipment_status_history h
                    WINDOW w AS (PARTITION BY h.equipment_id ORDER BY h.changed_at)
                ),
                operating AS (
                    SELECT i.equipment_id, greatest(i.starts, (:since AT TIME ZONE :tz)) AS starts,
                           i.ends
                    FROM intervals i
                    WHERE i.to_status = 'operacional' AND i.ends > (:since AT TIME ZONE :tz)
                )
                SELECT r.code AS region, e.type_code, d.day::date AS day,
                       sum(extract(epoch FROM least(o.ends, d.day + interval '1 day')
                                            - greatest(o.starts, d.day)) / 86400.0) AS device_days
                FROM operating o
                JOIN equipment e ON e.id = o.equipment_id
                JOIN regions r ON r.id = e.region_id
                CROSS JOIN LATERAL generate_series(
                    date_trunc('day', o.starts), date_trunc('day', o.ends), interval '1 day'
                ) AS d(day)
                WHERE least(o.ends, d.day + interval '1 day') > greatest(o.starts, d.day)
                GROUP BY 1, 2, 3
                """
            ),
            {"tz": tz, "since": since},
        )
        return [(r.region, r.type_code, r.day, float(r.device_days)) for r in rows]

    async def occurrences(self, tz: str, since: datetime) -> list[Occurrence]:
        rows = await self._session.execute(
            text(
                """
                SELECT (h.changed_at AT TIME ZONE :tz) AS at, r.code AS region, e.type_code
                FROM equipment_status_history h
                JOIN equipment e ON e.id = h.equipment_id
                JOIN regions r ON r.id = e.region_id
                WHERE h.to_status IN ('mau_funcionamento', 'furtado') AND h.changed_at >= :since
                """
            ),
            {"tz": tz, "since": since},
        )
        return [Occurrence(r.at, r.region, r.type_code) for r in rows]

    async def calendar(self, tz: str, since: datetime, until: datetime) -> list[EventWindow]:
        rows = await self._session.execute(
            text(
                """
                SELECT c.kind, r.code AS region, c.name,
                       (c.starts_at AT TIME ZONE :tz) AS starts_at,
                       (c.ends_at AT TIME ZONE :tz) AS ends_at,
                       c.expected_public
                FROM city_events c LEFT JOIN regions r ON r.id = c.region_id
                WHERE c.ends_at >= :since AND c.starts_at < :until
                ORDER BY c.starts_at
                """
            ),
            {"tz": tz, "since": since, "until": until},
        )
        return [EventWindow(r.kind, r.region, r.starts_at, r.ends_at, r.name) for r in rows]

    async def event_public(self, tz: str, since: datetime, until: datetime) -> list[dict[str, Any]]:
        rows = await self._session.execute(
            text(
                """
                SELECT c.name, c.kind, r.code AS region, c.expected_public,
                       (c.starts_at AT TIME ZONE :tz) AS starts_at,
                       (c.ends_at AT TIME ZONE :tz) AS ends_at
                FROM city_events c LEFT JOIN regions r ON r.id = c.region_id
                WHERE c.ends_at >= :since AND c.starts_at < :until
                ORDER BY c.starts_at
                """
            ),
            {"tz": tz, "since": since, "until": until},
        )
        return [dict(r._mapping) for r in rows]

    async def device_histories(self, tz: str) -> list[DeviceHistory]:
        rows = await self._session.execute(
            text(
                """
                SELECT e.id, e.type_code, p.interval_days,
                       (SELECT (min(h.changed_at) AT TIME ZONE :tz)::date
                        FROM equipment_status_history h
                        WHERE h.equipment_id = e.id AND h.to_status = 'operacional')
                         AS installed_on,
                       ARRAY(SELECT (h.changed_at AT TIME ZONE :tz)
                             FROM equipment_status_history h
                             WHERE h.equipment_id = e.id
                               AND h.to_status IN ('mau_funcionamento', 'furtado')
                             ORDER BY h.changed_at) AS failures,
                       ARRAY(SELECT (o.completed_at AT TIME ZONE :tz)::date
                             FROM maintenance_orders o
                             WHERE o.equipment_id = e.id AND o.kind = 'preventiva'
                               AND o.status = 'concluida'
                             ORDER BY o.completed_at) AS preventive
                FROM equipment e
                LEFT JOIN maintenance_plans p ON p.equipment_id = e.id
                WHERE e.archived_at IS NULL
                """
            ),
            {"tz": tz},
        )
        return [
            DeviceHistory(
                r.type_code,
                r.installed_on,
                tuple(r.failures),
                tuple(r.preventive),
                r.interval_days,
            )
            for r in rows
            if r.installed_on is not None
        ]

    async def devices_now(self, today: date) -> list[dict[str, Any]]:
        rows = await self._session.execute(
            text(
                """
                SELECT e.id, e.serial_number, e.type_code, t.name AS type_name,
                       r.code AS region, r.id AS region_id, e.neighborhood,
                       (p.next_due_date IS NOT NULL AND p.next_due_date < :today) AS overdue
                FROM equipment e
                JOIN equipment_types t ON t.code = e.type_code
                LEFT JOIN regions r ON r.id = e.region_id
                LEFT JOIN maintenance_plans p ON p.equipment_id = e.id
                WHERE e.archived_at IS NULL AND e.status = 'operacional'
                """
            ),
            {"today": today},
        )
        return [dict(r._mapping) for r in rows]

    async def availability_by_type(self, days: int) -> dict[str, list[tuple[date, float]]]:
        """Disponibilidade diária (% operacional entre os instalados) por tipo, no fim do dia."""
        rows = await self._session.execute(
            text(
                """
                WITH days AS (
                    SELECT generate_series(current_date - (:days - 1), current_date, '1 day')::date
                           AS day
                ),
                state AS (
                    SELECT d.day, e.type_code, last.to_status
                    FROM days d
                    CROSS JOIN equipment e
                    CROSS JOIN LATERAL (
                        SELECT h.to_status FROM equipment_status_history h
                        WHERE h.equipment_id = e.id
                          AND h.changed_at < (d.day + 1)::timestamptz
                        ORDER BY h.changed_at DESC LIMIT 1
                    ) last
                    WHERE e.archived_at IS NULL
                )
                SELECT day, type_code,
                       100.0 * count(*) FILTER (WHERE to_status = 'operacional')
                       / NULLIF(count(*) FILTER (WHERE to_status IN
                           ('operacional', 'mau_funcionamento', 'em_manutencao', 'furtado')), 0)
                       AS availability
                FROM state GROUP BY day, type_code ORDER BY day
                """
            ),
            {"days": days},
        )
        series: dict[str, list[tuple[date, float]]] = defaultdict(list)
        for r in rows:
            if r.availability is not None:
                series[r.type_code].append((r.day, float(r.availability)))
        return dict(series)

    async def equipment_with_open_preventive(self) -> set[UUID]:
        rows = await self._session.execute(
            text(
                "SELECT DISTINCT equipment_id FROM maintenance_orders "
                "WHERE kind = 'preventiva' AND status IN ('aberta', 'em_andamento')"
            )
        )
        return {r.equipment_id for r in rows}

    async def on_duty_by_region(self) -> dict[str, int]:
        rows = await self._session.execute(
            text(
                """
                SELECT r.code, count(*) AS n FROM agents a JOIN regions r ON r.id = a.region_id
                WHERE a.archived_at IS NULL AND a.is_active
                  AND a.duty_status IN ('disponivel', 'em_patrulha', 'em_ocorrencia', 'em_pausa')
                GROUP BY r.code
                """
            )
        )
        return {r.code: int(r.n) for r in rows}

    async def handling_minutes_by_region(self, days: int) -> dict[str, float]:
        rows = await self._session.execute(
            text(
                """
                SELECT r.code, avg(extract(epoch FROM (d.closed_at - d.created_at)) / 60) AS minutes
                FROM dispatches d JOIN equipment e ON e.id = d.equipment_id
                JOIN regions r ON r.id = e.region_id
                WHERE d.status = 'concluido' AND d.closed_at IS NOT NULL
                  AND d.created_at >= now() - make_interval(days => :days)
                GROUP BY r.code
                """
            ),
            {"days": days},
        )
        return {r.code: round(float(r.minutes), 1) for r in rows}

    async def live_occurrences_by_region(self, since: datetime) -> dict[str, int]:
        rows = await self._session.execute(
            text(
                """
                SELECT r.code, count(*) AS n FROM equipment_status_history h
                JOIN equipment e ON e.id = h.equipment_id JOIN regions r ON r.id = e.region_id
                WHERE h.to_status IN ('mau_funcionamento', 'furtado') AND h.changed_at >= :since
                GROUP BY r.code
                """
            ),
            {"since": since},
        )
        return {r.code: int(r.n) for r in rows}

    # ---- telemetria para anomalias --------------------------------------------------------

    async def telemetry_window(
        self, since: datetime, recent: datetime
    ) -> dict[UUID, dict[str, Any]]:
        """Leituras da última hora (linha de base) e a telemetria atual de cada equipamento."""
        rows = await self._session.execute(
            text(
                """
                SELECT e.id, e.type_code, e.serial_number, e.region_id, r.code AS region,
                       e.neighborhood, e.last_telemetry,
                       ARRAY(SELECT t.metrics FROM telemetry_readings t
                             WHERE t.equipment_id = e.id AND t.recorded_at >= :since
                               AND t.recorded_at < :recent) AS readings
                FROM equipment e LEFT JOIN regions r ON r.id = e.region_id
                WHERE e.archived_at IS NULL AND e.status = 'operacional'
                  AND e.last_seen_at >= :recent
                """
            ),
            {"since": since, "recent": recent},
        )
        return {
            r.id: {
                "type_code": r.type_code,
                "serial_number": r.serial_number,
                "region_id": r.region_id,
                "region": r.region,
                "neighborhood": r.neighborhood,
                "current": r.last_telemetry or {},
                "readings": list(r.readings or []),
            }
            for r in rows
        }

    async def open_detections(self) -> dict[UUID, tuple[int, datetime]]:
        rows = await self._session.execute(
            select(
                AnomalyDetectionModel.equipment_id,
                AnomalyDetectionModel.id,
                AnomalyDetectionModel.detected_at,
            ).where(AnomalyDetectionModel.outcome == "pendente")
        )
        return {r.equipment_id: (r.id, r.detected_at) for r in rows}

    async def add_detection(
        self, equipment_id: UUID, at: datetime, score: float, signals: dict[str, Any]
    ) -> None:
        await self._session.execute(
            insert(AnomalyDetectionModel).values(
                equipment_id=equipment_id, detected_at=at, score=score, signals=signals
            )
        )

    async def close_detection(self, equipment_id: UUID, outcome: str, at: datetime) -> bool:
        result = await self._session.execute(
            update(AnomalyDetectionModel)
            .where(
                AnomalyDetectionModel.equipment_id == equipment_id,
                AnomalyDetectionModel.outcome == "pendente",
            )
            .values(
                outcome=outcome,
                outcome_at=at,
                lead_minutes=func.extract("epoch", at - AnomalyDetectionModel.detected_at) / 60,
            )
            .returning(AnomalyDetectionModel.id)
        )
        return result.first() is not None

    async def expire_detections(self, older_than: datetime, at: datetime) -> list[UUID]:
        result = await self._session.execute(
            update(AnomalyDetectionModel)
            .where(
                AnomalyDetectionModel.outcome == "pendente",
                AnomalyDetectionModel.detected_at < older_than,
            )
            .values(outcome="falso_alarme", outcome_at=at)
            .returning(AnomalyDetectionModel.equipment_id)
        )
        return [row[0] for row in result]

    async def labeled_detections(self, limit: int) -> list[LabeledDetection]:
        """Detecções com desfecho (rótulos do classificador): falhou/evitada = falha real."""
        rows = await self._session.execute(
            text(
                """
                SELECT d.detected_at, d.signals, d.outcome, e.type_code
                FROM anomaly_detections d JOIN equipment e ON e.id = d.equipment_id
                WHERE d.outcome IN ('falhou', 'evitada', 'falso_alarme')
                ORDER BY d.detected_at DESC LIMIT :limit
                """
            ),
            {"limit": limit},
        )
        samples = []
        for r in rows:
            z = dict(r.signals.get("z") or {})
            for signal in r.signals.get("signals") or []:  # detecções antigas: só os sinais
                z.setdefault(signal["metric"], float(signal["z"]))
            samples.append(
                LabeledDetection(r.detected_at, z, r.type_code, r.outcome != "falso_alarme")
            )
        return samples

    async def detection_quality(self, since: datetime) -> dict[str, Any]:
        row = (
            await self._session.execute(
                text(
                    """
                    SELECT
                      count(*) FILTER (WHERE outcome = 'falhou') AS failed,
                      count(*) FILTER (WHERE outcome = 'evitada') AS averted,
                      count(*) FILTER (WHERE outcome = 'falso_alarme') AS false_alarms,
                      count(*) FILTER (WHERE outcome = 'pendente') AS pending,
                      avg(lead_minutes) FILTER (WHERE outcome = 'falhou') AS lead,
                      (SELECT count(*) FROM equipment_status_history h
                        WHERE h.to_status IN ('mau_funcionamento', 'furtado')
                          AND h.changed_at >= :since
                          AND h.changed_by IS NULL) AS live_failures
                    FROM anomaly_detections WHERE detected_at >= :since
                    """
                ),
                {"since": since},
            )
        ).one()
        return dict(row._mapping)

    async def record_averted(self, equipment_id: UUID, at: datetime, intervention: str) -> None:
        """Liga a falha evitada à decisão do PROMETHEUS que a causou (se houver)."""
        decision = (
            await self._session.execute(
                text(
                    """
                    SELECT id FROM agent_decisions
                    WHERE equipment_id = :equipment AND status = 'executada'
                      AND created_at >= :at - interval '2 hours'
                    ORDER BY created_at DESC LIMIT 1
                    """
                ),
                {"equipment": equipment_id, "at": at},
            )
        ).scalar_one_or_none()
        await self._session.execute(
            insert(AvertedFaultModel).values(
                equipment_id=equipment_id,
                averted_at=at,
                intervention=intervention,
                decision_id=decision,
                by_prometheus=decision is not None,
            )
        )

    async def averted_counts(self, since: datetime) -> dict[str, int]:
        row = (
            await self._session.execute(
                text(
                    """
                    SELECT count(*) AS total, count(*) FILTER (WHERE by_prometheus) AS prometheus
                    FROM averted_faults WHERE averted_at >= :since
                    """
                ),
                {"since": since},
            )
        ).one()
        return {"total": int(row.total), "by_prometheus": int(row.prometheus)}

    # ---- modelos e snapshots ---------------------------------------------------------------

    async def save_model(
        self,
        kind: str,
        fitted_at: datetime,
        training_from: datetime,
        training_to: datetime,
        params: dict[str, Any],
        metrics: dict[str, Any],
    ) -> int:
        result = await self._session.execute(
            insert(PredictionModelRun)
            .values(
                kind=kind,
                fitted_at=fitted_at,
                training_from=training_from,
                training_to=training_to,
                params=params,
                metrics=metrics,
            )
            .returning(PredictionModelRun.id)
        )
        return int(result.scalar_one())

    async def latest_model(self, kind: str) -> ModelRun | None:
        stmt = (
            select(PredictionModelRun)
            .where(PredictionModelRun.kind == kind)
            .order_by(PredictionModelRun.fitted_at.desc())
            .limit(1)
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return ModelRun(row.id, row.fitted_at, row.params, row.metrics) if row else None

    async def save_snapshot(
        self, kind: str, at: datetime, payload: dict[str, Any], model_id: int | None
    ) -> None:
        await self._session.execute(
            text(
                """
                INSERT INTO prediction_snapshots (kind, generated_at, model_id, payload)
                VALUES (:kind, :at, :model, CAST(:payload AS jsonb))
                ON CONFLICT (kind) DO UPDATE
                SET generated_at = EXCLUDED.generated_at, model_id = EXCLUDED.model_id,
                    payload = EXCLUDED.payload
                """
            ),
            {"kind": kind, "at": at, "model": model_id, "payload": _json(payload)},
        )

    async def get_snapshot(self, kind: str) -> Snapshot | None:
        row = await self._session.get(PredictionSnapshotModel, kind)
        return Snapshot(row.kind, row.generated_at, row.payload) if row else None


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, default=str, ensure_ascii=False)
