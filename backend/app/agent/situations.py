"""O que PROMETHEUS percebe: transforma previsões e anomalias em situações acionáveis.

Cada situação traz uma ``confidence`` que é uma probabilidade medida, não opinião:
- precursor de falha: precisão observada das detecções (acertos ÷ decididas), com prior Beta(3, 1);
- pico regional: 1 − p-valor do teste binomial;
- risco em 72 h: a probabilidade do modelo de equipamentos;
- déficit de efetivo: proporção do déficit sobre o recomendado.
"""

from typing import Any
from uuid import UUID

from app.domain.prometheus.entities import SITUATION_LABELS, Situation, SituationKind

PRIOR_HITS, PRIOR_MISSES = 3.0, 1.0
MAX_EQUIPMENT_RISK_SITUATIONS = 3
EQUIPMENT_RISK_MIN_PROBABILITY = 0.08


def precursor_confidence(quality: dict[str, Any]) -> float:
    hits = (quality.get("detections_confirmed") or 0) + (quality.get("detections_averted") or 0)
    misses = quality.get("false_alarms") or 0
    return round((hits + PRIOR_HITS) / (hits + misses + PRIOR_HITS + PRIOR_MISSES), 3)


def build_situations(
    city: dict[str, Any] | None,
    anomalies: dict[str, Any] | None,
    region_ids: dict[str, UUID],
    region_names: dict[str, str],
) -> list[Situation]:
    situations: list[Situation] = []
    if anomalies:
        confidence = precursor_confidence(anomalies.get("quality") or {})
        for device in anomalies.get("devices") or []:
            signals = ", ".join(
                f"{s['label'].lower()} {s['value']} (normal ≈ {s['baseline']})"
                for s in device["signals"]
            )
            situations.append(
                Situation(
                    key=f"precursor:{device['equipment_id']}",
                    kind=SituationKind.PRECURSOR_FALHA,
                    title=(
                        f"{SITUATION_LABELS[SituationKind.PRECURSOR_FALHA]}: "
                        f"{device['type_code']} {device['serial_number']}"
                    ),
                    summary=(
                        f"Telemetria fora do padrão em {device['neighborhood']} "
                        f"({region_names.get(device['region'] or '', '—')}): {signals}. "
                        "Padrão que costuma anteceder a falha em poucos minutos."
                    ),
                    # Probabilidade do classificador aprendido; sem ele, a precisão observada.
                    confidence=device.get("p_real") or confidence,
                    equipment_id=UUID(device["equipment_id"]),
                    region_id=region_ids.get(device["region"] or ""),
                    region_code=device["region"],
                    type_code=device["type_code"],
                    facts={
                        "anomaly_score": device["score"],
                        "signals": device["signals"],
                        "p_real": device.get("p_real"),
                    },
                )
            )
        for finding in anomalies.get("regional") or []:
            code = finding["region"]
            hotspot = _hotspot_equipment(city, code)
            situations.append(
                Situation(
                    key=f"pico:{code}",
                    kind=SituationKind.PICO_REGIONAL,
                    title=f"{SITUATION_LABELS[SituationKind.PICO_REGIONAL]}: {region_names[code]}",
                    summary=(
                        f"{finding['observed']} ocorrências nas últimas 3 h na região "
                        f"{region_names[code]}, contra {finding['expected']} esperadas pela "
                        f"participação histórica (p = {finding['p_value']})."
                    ),
                    confidence=round(min(0.99, 1 - float(finding["p_value"])), 3),
                    region_id=region_ids.get(code),
                    region_code=code,
                    equipment_id=None,
                    facts={**finding, "hotspot_equipment_id": hotspot},
                )
            )
    if city:
        # Prioriza pelo impacto (probabilidade × peso do tipo): semáforo antes de patinete.
        risky = [
            d
            for d in city.get("equipment_priority") or city.get("equipment_risk") or []
            if d["probability_72h"] >= EQUIPMENT_RISK_MIN_PROBABILITY
        ][:MAX_EQUIPMENT_RISK_SITUATIONS]
        for device in risky:
            top = ", ".join(f"{f['factor']} ×{f['multiplier']}" for f in device["factors"][:3])
            situations.append(
                Situation(
                    key=f"risco72:{device['equipment_id']}",
                    kind=SituationKind.RISCO_EQUIPAMENTO,
                    title=(
                        f"{SITUATION_LABELS[SituationKind.RISCO_EQUIPAMENTO]}: "
                        f"{device['type_name']} {device['serial_number']}"
                    ),
                    summary=(
                        f"Probabilidade de falha de {device['probability_72h']:.0%} nas próximas "
                        f"72 h em {device['neighborhood']}. Principais fatores: {top}."
                    ),
                    confidence=float(device["probability_72h"]),
                    equipment_id=UUID(device["equipment_id"]),
                    region_id=region_ids.get(device["region"] or ""),
                    region_code=device["region"],
                    type_code=device["type_code"],
                    facts={
                        "probability_72h": device["probability_72h"],
                        "overdue": device["overdue"],
                    },
                )
            )
        blocks = city.get("reinforcement") or []
        if blocks:
            block = blocks[0]
            rows = {r["region"]: r for r in block["regions"]}
            for move in _merge_moves(block.get("moves") or []):
                target = rows[move["to"]]
                situations.append(
                    Situation(
                        key=f"deficit:{move['to']}:{block['starts_at']}",
                        kind=SituationKind.DEFICIT_EFETIVO,
                        title=(
                            f"{SITUATION_LABELS[SituationKind.DEFICIT_EFETIVO]}: "
                            f"{region_names[move['to']]}"
                        ),
                        summary=_deficit_summary(block, target, move, region_names),
                        confidence=round(
                            min(0.95, target["gap"] / max(target["recommended"], 1)), 3
                        ),
                        region_id=region_ids.get(move["to"]),
                        region_code=move["to"],
                        facts={
                            "from_region": move["from"],
                            "to_region": move["to"],
                            "agents": move["agents"],
                            "window": f"{block['starts_at']}/{block['ends_at']}",
                            "hotspot_equipment_id": _hotspot_equipment(city, move["to"]),
                        },
                    )
                )
    return situations


def _hotspot_equipment(city: dict[str, Any] | None, region: str) -> str | None:
    for device in (city or {}).get("equipment_risk") or []:
        if device["region"] == region:
            return str(device["equipment_id"])
    return None


def _deficit_summary(
    block: dict[str, Any],
    target: dict[str, Any],
    move: dict[str, Any],
    names: dict[str, str],
) -> str:
    window = f"{block['starts_at'][11:16]} e {block['ends_at'][11:16]}"
    return (
        f"Entre {window}, a região {names[move['to']]} deveria ter {target['recommended']} "
        f"agentes e tem {target['staffed']} ({target['reason'].lower()}). "
        f"Sugestão: mover {move['agents']} de {names[move['from']]}."
    )


def _merge_moves(moves: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Uma situação por região de destino (soma os agentes; origem = a que mais cede)."""
    merged: dict[str, dict[str, Any]] = {}
    for move in moves:
        current = merged.get(move["to"])
        if current is None:
            merged[move["to"]] = dict(move)
            continue
        if move["agents"] > current["agents"]:
            current["from"] = move["from"]
        current["agents"] += move["agents"]
    return list(merged.values())
