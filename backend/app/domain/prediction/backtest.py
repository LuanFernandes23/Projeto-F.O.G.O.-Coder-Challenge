"""Backtest e calibração: o modelo prevê um período que ele não viu e é comparado com o real.

Sem isso a previsão seria um chute com cara de ciência. Métricas (sobre células região ×
dia × faixa de 4 h, onde a contagem deixa de ser quase sempre zero):

- desvio de Poisson e erro absoluto médio do modelo contra duas linhas de base ingênuas:
  "média histórica" (taxa constante) e "perfil por hora" (só a hora do dia);
- skill = 1 − desvio(modelo) / desvio(linha de base): > 0 significa que o modelo é melhor;
- cobertura top-20%: fração das ocorrências reais que caíram nos 20% de células que o modelo
  apontou como mais arriscadas (a pergunta prática do gestor: "olhando só o que o modelo
  destaca, quanto eu pego?");
- calibração: probabilidade prevista × frequência observada, por faixas. Ela transforma a
  probabilidade bruta em "confiança calibrada", usada pela política de autonomia.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from typing import Any

import numpy as np

from app.domain.prediction.risk_model import (
    BLOCK_HOURS,
    BLOCKS,
    HOURS,
    FloatArray,
    Grid,
    RiskModel,
    expected_cube,
)

CALIBRATION_BINS = (0.0, 0.05, 0.1, 0.2, 0.3, 0.45, 0.6, 0.8, 1.0001)


def _to_blocks(cube: FloatArray) -> FloatArray:
    """[R, G, D, H] → [R, D, BLOCKS] (soma os grupos e as horas de cada faixa)."""
    by_region = cube.sum(axis=1)
    r, d, _ = by_region.shape
    return np.asarray(by_region.reshape(r, d, BLOCKS, BLOCK_HOURS).sum(axis=3))


def poisson_deviance(observed: FloatArray, expected: FloatArray) -> float:
    mu = np.maximum(expected, 1e-9)
    y = observed
    term = np.where(y > 0, y * np.log(np.where(y > 0, y, 1.0) / mu), 0.0) - (y - mu)
    return float(2.0 * term.sum())


@dataclass(frozen=True, slots=True)
class Calibration:
    """Mapa probabilidade prevista → frequência observada (monótono)."""

    edges: tuple[float, ...]
    observed: tuple[float, ...]  # frequência observada por faixa (monótona não decrescente)
    predicted: tuple[float, ...]  # probabilidade média prevista por faixa
    counts: tuple[int, ...]

    def calibrate(self, probability: float) -> float:
        for i in range(len(self.edges) - 1):
            if self.edges[i] <= probability < self.edges[i + 1]:
                if self.counts[i] == 0:
                    return probability
                return self.observed[i]
        return probability

    def as_dict(self) -> dict[str, Any]:
        return {
            "edges": list(self.edges),
            "observed": [round(v, 4) for v in self.observed],
            "predicted": [round(v, 4) for v in self.predicted],
            "counts": list(self.counts),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Calibration:
        return cls(
            tuple(data["edges"]),
            tuple(data["observed"]),
            tuple(data["predicted"]),
            tuple(data["counts"]),
        )


def calibration(probabilities: FloatArray, hits: FloatArray) -> Calibration:
    edges = CALIBRATION_BINS
    observed: list[float] = []
    predicted: list[float] = []
    counts: list[int] = []
    for low, high in pairwise(edges):
        mask = (probabilities >= low) & (probabilities < high)
        n = int(mask.sum())
        counts.append(n)
        predicted.append(float(probabilities[mask].mean()) if n else (low + high) / 2)
        observed.append(float(hits[mask].mean()) if n else (low + high) / 2)
    # Garante monotonia (frequência não pode cair quando a probabilidade sobe): média acumulada
    # das faixas vizinhas, como um isotônico simples.
    for i in range(1, len(observed)):
        if observed[i] < observed[i - 1]:
            pooled = (observed[i] * counts[i] + observed[i - 1] * counts[i - 1]) / max(
                counts[i] + counts[i - 1], 1
            )
            observed[i] = observed[i - 1] = pooled
    return Calibration(edges, tuple(observed), tuple(predicted), tuple(counts))


def evaluate(model: RiskModel, train: Grid, test: Grid) -> dict[str, Any]:
    """Métricas do modelo no período de teste, contra linhas de base ajustadas no treino."""
    observed = _to_blocks(test.counts)
    expected = _to_blocks(expected_cube(model, test))

    exposure_hours_train = train.exposure.sum() * HOURS
    mean_rate = train.counts.sum() / max(exposure_hours_train, 1e-9)
    naive = _to_blocks(test.exposure[:, :, :, None] * np.full(HOURS, mean_rate)[None, None, None])

    hour_totals = train.counts.sum(axis=(0, 1, 2))
    hour_rate = hour_totals / max(train.exposure.sum(), 1e-9)
    by_hour = _to_blocks(test.exposure[:, :, :, None] * hour_rate[None, None, None, :])

    dev_model = poisson_deviance(observed, expected)
    dev_naive = poisson_deviance(observed, naive)
    dev_hour = poisson_deviance(observed, by_hour)

    probability = 1.0 - np.exp(-expected)
    hits = (observed > 0).astype(np.float64)
    calib = calibration(probability.ravel(), hits.ravel())

    flat_expected, flat_observed = expected.ravel(), observed.ravel()
    order = np.argsort(-flat_expected)
    top = order[: max(1, int(len(order) * 0.2))]
    total_observed = float(flat_observed.sum())
    capture = float(flat_observed[top].sum() / total_observed) if total_observed else 0.0

    return {
        "test_days": len(test.days),
        "test_events": int(total_observed),
        "deviance": {
            "model": round(dev_model, 2),
            "baseline_mean": round(dev_naive, 2),
            "baseline_hour": round(dev_hour, 2),
        },
        "skill_vs_mean": round(1 - dev_model / dev_naive, 4) if dev_naive else 0.0,
        "skill_vs_hour": round(1 - dev_model / dev_hour, 4) if dev_hour else 0.0,
        "mae": {
            "model": round(float(np.abs(observed - expected).mean()), 4),
            "baseline_mean": round(float(np.abs(observed - naive).mean()), 4),
            "baseline_hour": round(float(np.abs(observed - by_hour).mean()), 4),
        },
        "top20_capture": round(capture, 4),
        "calibration": calib.as_dict(),
    }
