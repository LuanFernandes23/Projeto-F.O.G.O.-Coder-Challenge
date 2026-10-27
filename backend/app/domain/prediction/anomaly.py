"""Detecção de comportamento fora do padrão (estatística robusta, sem "caixa-preta").

1. Por equipamento: cada métrica atual é comparada com a mediana da última hora do próprio
   equipamento, em desvios robustos (MAD × 1,4826). Só conta o lado ruim (temperatura
   subindo, sinal e uptime caindo). Anomalia = 2+ métricas com z ≥ 3, ou uma com z ≥ 6.
2. Por região: a participação da região nas ocorrências das últimas horas é comparada com a
   participação prevista pelo modelo de risco (teste binomial exato). Comparar participação, e
   não o volume, torna o teste imune ao volume total (ex.: a simulação acelerada da demo).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

# métrica: (direção ruim, piso do desvio, rótulo)
METRICS: dict[str, tuple[int, float, str]] = {
    "temperature_c": (+1, 1.0, "Temperatura"),
    "signal_dbm": (-1, 2.0, "Sinal"),
    "uptime_pct": (-1, 0.25, "Disponibilidade do link"),
}
Z_SIGNAL = 3.0
Z_STRONG = 6.0


@dataclass(frozen=True, slots=True)
class Baseline:
    median: float
    mad: float
    samples: int


@dataclass(frozen=True, slots=True)
class AnomalyScore:
    score: float  # 0-1
    is_anomaly: bool
    signals: list[dict[str, Any]]
    z: dict[str, float] = field(
        default_factory=dict
    )  # todas as métricas (entrada do classificador)


def median_mad(values: list[float]) -> Baseline:
    """Mediana e desvio absoluto mediano (resistentes a valores extremos)."""
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return Baseline(0.0, 0.0, 0)
    median = (ordered[(n - 1) // 2] + ordered[n // 2]) / 2
    deviations = sorted(abs(v - median) for v in ordered)
    return Baseline(median, (deviations[(n - 1) // 2] + deviations[n // 2]) / 2, n)


def robust_z(value: float, baseline: Baseline, direction: int, floor: float) -> float:
    spread = max(1.4826 * baseline.mad, floor)
    return direction * (value - baseline.median) / spread


def score_device(current: dict[str, Any], baselines: dict[str, Baseline]) -> AnomalyScore:
    signals: list[dict[str, Any]] = []
    all_z: dict[str, float] = {}
    for metric, (direction, floor, label) in METRICS.items():
        value, baseline = current.get(metric), baselines.get(metric)
        if not isinstance(value, int | float) or baseline is None or baseline.samples < 4:
            continue
        z = robust_z(float(value), baseline, direction, floor)
        all_z[metric] = round(z, 2)
        if z >= Z_SIGNAL:
            signals.append(
                {
                    "metric": metric,
                    "label": label,
                    "value": value,
                    "baseline": round(baseline.median, 2),
                    "z": round(z, 1),
                }
            )
    signals.sort(key=lambda s: s["z"], reverse=True)
    strongest = [s["z"] for s in signals[:2]]
    is_anomaly = len(signals) >= 2 or bool(signals and signals[0]["z"] >= Z_STRONG)
    score = min(1.0, sum(strongest) / (2 * 2 * Z_STRONG)) if strongest else 0.0
    return AnomalyScore(round(score, 3), is_anomaly, signals, all_z)


def binomial_upper_tail(k: int, n: int, p: float) -> float:
    """P(X ≥ k) para X ~ Binomial(n, p), exato (n pequeno)."""
    if k <= 0:
        return 1.0
    p = min(max(p, 1e-9), 1 - 1e-9)
    return float(sum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k, n + 1)))


def regional_surprise(
    observed: dict[str, int], expected_share: dict[str, float], *, alpha: float = 0.01
) -> list[dict[str, Any]]:
    """Regiões com mais ocorrências do que a participação prevista explicaria."""
    total = sum(observed.values())
    findings: list[dict[str, Any]] = []
    if total < 5:
        return findings
    for region, count in observed.items():
        share = expected_share.get(region, 0.0)
        p_value = binomial_upper_tail(count, total, share)
        expected = share * total
        if count >= 4 and p_value < alpha and count > expected * 1.5:
            findings.append(
                {
                    "region": region,
                    "observed": count,
                    "expected": round(expected, 1),
                    "ratio": round(count / max(expected, 0.1), 2),
                    "p_value": round(p_value, 5),
                }
            )
    findings.sort(key=lambda f: f["p_value"])
    return findings
