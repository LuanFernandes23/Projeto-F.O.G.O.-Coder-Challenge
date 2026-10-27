"""Classificador de precursores que aprende com os próprios desfechos (ML com rótulo real).

Cada detecção termina em ``falhou`` ou ``evitada`` (era falha de verdade) ou ``falso_alarme``.
Esses desfechos são rótulos que crescem com o uso: a regressão logística aprende quais
combinações de sinais antecedem falhas e devolve, para cada nova detecção, a probabilidade de
ser falha real. Essa probabilidade é a "confiança" que a política de autonomia usa.

Por que regressão logística (e não boosting): com dezenas a centenas de rótulos ela é estável,
calibrada por construção e os pesos são legíveis ("queda de link pesa mais que temperatura").
Avaliação temporal: treina nas detecções mais antigas e testa nas mais recentes (sem olhar o
futuro), comparando com a linha de base "toda detecção é falha" (a regra atual).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np

from app.domain.prediction.risk_model import group_of

FEATURES = (
    "intercepto",
    "temperatura",
    "sinal",
    "uptime",
    "sinais_fortes",
    "trânsito",
    "espaço público",
)
FEATURE_LABELS = {
    "temperatura": "aquecimento",
    "sinal": "queda de sinal",
    "uptime": "queda de disponibilidade do link",
    "sinais_fortes": "número de sinais fortes",
    "trânsito": "equipamento de trânsito",
    "espaço público": "equipamento em espaço público",
}
MIN_LABELS = 30
MIN_PER_CLASS = 5
L2 = 1.0
Z_CAP = 12.0


@dataclass(frozen=True, slots=True)
class LabeledDetection:
    detected_at: datetime
    z: dict[str, float]
    type_code: str
    real: bool


def features(z: dict[str, float], type_code: str) -> list[float]:
    def cap(value: float) -> float:
        return max(-Z_CAP, min(Z_CAP, value)) / Z_CAP

    group = group_of(type_code)
    strong = sum(1 for v in z.values() if v >= 3)
    return [
        1.0,
        cap(z.get("temperature_c", 0.0)),
        cap(z.get("signal_dbm", 0.0)),
        cap(z.get("uptime_pct", 0.0)),
        strong / 3,
        1.0 if group == "transito" else 0.0,
        1.0 if group == "espaco_publico" else 0.0,
    ]


def _sigmoid(x: Any) -> Any:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -30, 30)))


def fit_logistic(x: np.ndarray, y: np.ndarray, l2: float = L2) -> np.ndarray:
    """Newton-Raphson (IRLS) com regularização L2 (o intercepto não é penalizado)."""
    w = np.zeros(x.shape[1])
    penalty = np.eye(x.shape[1]) * l2
    penalty[0, 0] = 0.0
    for _ in range(50):
        p = _sigmoid(x @ w)
        gradient = x.T @ (p - y) + penalty @ w
        hessian = (x.T * (p * (1 - p))) @ x + penalty
        step = np.linalg.solve(hessian + np.eye(len(w)) * 1e-9, gradient)
        w -= step
        if float(np.abs(step).max()) < 1e-6:
            break
    return w


def auc(scores: Sequence[float], labels: Sequence[bool]) -> float | None:
    pos = [s for s, y in zip(scores, labels, strict=True) if y]
    neg = [s for s, y in zip(scores, labels, strict=True) if not y]
    if not pos or not neg:
        return None
    wins = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


@dataclass(frozen=True, slots=True)
class PrecursorModel:
    weights: tuple[float, ...]
    trained_on: int
    metrics: dict[str, Any]

    def probability(self, z: dict[str, float], type_code: str) -> float:
        x = np.asarray(features(z, type_code))
        return float(_sigmoid(x @ np.asarray(self.weights)))

    def explain(self) -> list[dict[str, Any]]:
        """Peso de cada sinal (razão de chances: >1 aumenta a chance de ser falha real)."""
        items: list[dict[str, Any]] = []
        for name, weight in zip(FEATURES[1:], self.weights[1:], strict=True):
            items.append(
                {
                    "feature": FEATURE_LABELS[name],
                    "weight": round(weight, 3),
                    "odds_ratio": round(math.exp(weight), 2),
                }
            )
        items.sort(key=lambda i: abs(float(i["weight"])), reverse=True)
        return items

    def as_params(self) -> dict[str, Any]:
        return {"weights": list(self.weights), "features": list(FEATURES), "n": self.trained_on}

    @classmethod
    def from_params(cls, params: dict[str, Any], metrics: dict[str, Any]) -> PrecursorModel:
        return cls(tuple(params["weights"]), int(params["n"]), metrics)


def train(samples: Sequence[LabeledDetection]) -> PrecursorModel | None:
    """Treina com tudo e mede num corte temporal (70% mais antigo → 30% mais recente)."""
    positives = sum(1 for s in samples if s.real)
    negatives = len(samples) - positives
    if len(samples) < MIN_LABELS or min(positives, negatives) < MIN_PER_CLASS:
        return None
    ordered = sorted(samples, key=lambda s: s.detected_at)
    cut = int(len(ordered) * 0.7)
    train_set, test_set = ordered[:cut], ordered[cut:]

    def matrix(items: Sequence[LabeledDetection]) -> tuple[np.ndarray, np.ndarray]:
        x = np.asarray([features(s.z, s.type_code) for s in items])
        y = np.asarray([1.0 if s.real else 0.0 for s in items])
        return x, y

    metrics: dict[str, Any] = {"labels": len(samples), "real": positives, "false": negatives}
    if len({s.real for s in train_set}) == 2 and test_set:
        x_train, y_train = matrix(train_set)
        x_test, y_test = matrix(test_set)
        w = fit_logistic(x_train, y_train)
        p = _sigmoid(x_test @ w)
        base_rate = float(y_train.mean())
        predicted_real = p >= 0.5
        kept = int(predicted_real.sum())
        metrics.update(
            {
                "test_size": len(test_set),
                "auc": None
                if (a := auc(p.tolist(), y_test.astype(bool).tolist())) is None
                else round(a, 3),
                "brier": round(float(np.mean((p - y_test) ** 2)), 4),
                "brier_baseline": round(float(np.mean((base_rate - y_test) ** 2)), 4),
                "precision_rule": round(float(y_test.mean()), 3),
                "precision_model": round(float(y_test[predicted_real].mean()), 3) if kept else None,
                "recall_model": round(float(predicted_real[y_test == 1].mean()), 3)
                if (y_test == 1).any()
                else None,
            }
        )
    x_all, y_all = matrix(ordered)
    return PrecursorModel(
        tuple(float(v) for v in fit_logistic(x_all, y_all)), len(samples), metrics
    )
