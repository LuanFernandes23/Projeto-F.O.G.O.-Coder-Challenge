"""Onde posicionar o efetivo: distribuição recomendada × escala prevista, por região e faixa.

A recomendação parte de duas regras explícitas (ambas documentadas na base de conhecimento):

1. Proporcionalidade ao risco: o efetivo disponível na faixa é distribuído conforme a
   participação de cada região nas ocorrências previstas pelo modelo de risco, com um piso
   mínimo por região (nenhuma região fica descoberta).
2. Eventos: público esperado exige efetivo mínimo (``AGENTS_PER_THOUSAND`` por mil pessoas).

O déficit é a diferença entre o recomendado e o escalado (observado na mesma faixa da semana
anterior). As sugestões de remanejamento movem agentes de regiões com sobra para as com falta.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

MIN_SHARE = 0.08  # piso por região (8% do efetivo da faixa)
AGENTS_PER_THOUSAND = 0.5  # 1 agente a cada 2.000 pessoas em eventos
MIN_GAP_TO_ACT = 2  # diferenças menores que isso não justificam remanejar


@dataclass(frozen=True, slots=True)
class RegionWindow:
    region: str
    expected_occurrences: float
    staffed: int  # agentes em serviço escalados na faixa
    event_public: int = 0
    event_names: tuple[str, ...] = ()


def recommend(windows: Sequence[RegionWindow]) -> dict[str, Any]:
    total_staff = sum(w.staffed for w in windows)
    total_expected = sum(w.expected_occurrences for w in windows) or 1.0
    shares = {w.region: max(w.expected_occurrences / total_expected, MIN_SHARE) for w in windows}
    norm = sum(shares.values()) or 1.0
    rows: list[dict[str, Any]] = []
    for w in windows:
        proportional = total_staff * shares[w.region] / norm
        for_event = math.ceil(w.event_public / 1000 * AGENTS_PER_THOUSAND)
        recommended = max(round(proportional), for_event)
        rows.append(
            {
                "region": w.region,
                "expected_occurrences": round(w.expected_occurrences, 2),
                "risk_share": round(w.expected_occurrences / total_expected, 3),
                "staffed": w.staffed,
                "recommended": recommended,
                "gap": recommended - w.staffed,
                "event_public": w.event_public,
                "events": list(w.event_names),
                "reason": (
                    f"Evento com {_thousands(w.event_public)} pessoas exige ao menos "
                    f"{for_event} agentes"
                    if for_event > round(proportional)
                    else "Proporcional ao risco previsto"
                ),
            }
        )
    moves = _moves(rows)
    return {"regions": rows, "moves": moves, "total_staff": total_staff}


def _thousands(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def _moves(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    surplus = sorted(
        ({"region": r["region"], "free": -r["gap"]} for r in rows if r["gap"] <= -MIN_GAP_TO_ACT),
        key=lambda s: -s["free"],
    )
    deficit = sorted(
        ({"region": r["region"], "need": r["gap"]} for r in rows if r["gap"] >= MIN_GAP_TO_ACT),
        key=lambda d: -d["need"],
    )
    moves: list[dict[str, Any]] = []
    for d in deficit:
        for s in surplus:
            if d["need"] <= 0:
                break
            amount = min(d["need"], s["free"])
            if amount <= 0:
                continue
            moves.append({"from": s["region"], "to": d["region"], "agents": amount})
            d["need"] -= amount
            s["free"] -= amount
    return moves
