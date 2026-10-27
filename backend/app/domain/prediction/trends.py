"""Tendência de disponibilidade: inclinação robusta (Theil–Sen) e projeção de limite.

Theil–Sen usa a mediana das inclinações entre todos os pares de pontos: um dia atípico
(ex.: um furto em massa) não distorce a tendência como faria uma regressão linear comum.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

MIN_POINTS = 14


def theil_sen(values: Sequence[float]) -> tuple[float, float]:
    """(inclinação por dia, intercepto) da série com x = 0, 1, 2…"""
    n = len(values)
    slopes = [(values[j] - values[i]) / (j - i) for i in range(n) for j in range(i + 1, n) if j > i]
    slope = statistics.median(slopes) if slopes else 0.0
    intercept = statistics.median(v - slope * x for x, v in enumerate(values))
    return slope, intercept


def project(
    series: Sequence[tuple[date, float]], threshold: float, horizon_days: int = 90
) -> dict[str, Any]:
    """Tendência da série (em %) e quando ela cruza ``threshold`` se nada mudar."""
    if len(series) < MIN_POINTS:
        return {"slope_per_week": 0.0, "crosses_on": None, "status": "dados_insuficientes"}
    values = [v for _, v in series]
    slope, intercept = theil_sen(values)
    last_x = len(values) - 1
    fitted_now = intercept + slope * last_x
    crosses_on: date | None = None
    if slope < 0 and fitted_now > threshold:
        days = (fitted_now - threshold) / -slope
        if days <= horizon_days:
            crosses_on = series[-1][0] + timedelta(days=round(days))
    elif fitted_now <= threshold:
        crosses_on = series[-1][0]
    weekly = slope * 7
    status = "queda" if weekly <= -0.3 else "alta" if weekly >= 0.3 else "estavel"
    return {
        "slope_per_week": round(weekly, 3),
        "current_fitted": round(fitted_now, 2),
        "crosses_on": crosses_on.isoformat() if crosses_on else None,
        "status": status,
        "projection": [
            {
                "date": (series[-1][0] + timedelta(days=d)).isoformat(),
                "value": round(fitted_now + slope * d, 2),
            }
            for d in (0, 7, 14, 21, 28)
        ],
    }
