"""Modelo de risco de ocorrências por região × dia × hora (Poisson multiplicativo).

Ideia: a taxa esperada de ocorrências numa célula (região, grupo de equipamento, dia, hora)
é a exposição (equipamentos instalados) vezes fatores multiplicativos aprendidos do histórico:

    λ = exposição × base[grupo] × região[r] × hora[h] × semana[grupo, dia, faixa]
        × mês[grupo, mês] × evento[grupo, tipo de evento]

Os fatores são ajustados por "raking" (IPF): cada fator é corrigido pela razão
observado/esperado na sua margem, até convergir. Cada fator é encolhido em direção a 1
(empirical Bayes, prior Gamma com força ``SHRINK_EVENTS``), para não exagerar onde há poucos
dados. Tudo é explicável: a previsão de uma célula é o produto de fatores com nome.

O módulo é puro (numpy) e não conhece os parâmetros da simulação: aprende só do histórico.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]

HOURS = 24
BLOCK_HOURS = 4  # faixas de 4 h para a interação dia da semana × horário
BLOCKS = HOURS // BLOCK_HOURS
SHRINK_EVENTS = 3.0  # força do prior: quantos "eventos fictícios" puxam o fator para 1
SHRINK_FINE_EVENTS = 8.0  # fatores finos (tipo de dia × faixa, mês): prior mais forte
# Tipos de dia: os padrões de cidade mudam entre dias úteis, sexta, sábado e domingo.
DAY_TYPES = ("dia útil", "sexta", "sábado", "domingo")
_DAY_TYPE_OF_WEEKDAY = (0, 0, 0, 0, 1, 2, 3)
EVENT_KINDS = ("nenhum", "feriado", "esporte", "cultura", "feira")
WEEKDAY_LABELS = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")
MONTH_LABELS = (
    "jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez",
)  # fmt: skip

# Grupos de equipamento por natureza da operação (conhecimento do domínio, não da simulação).
TYPE_GROUPS: dict[str, str] = {
    "semaforo": "transito",
    "radar": "transito",
    "cancela": "transito",
    "balanca": "transito",
    "camera": "espaco_publico",
    "totem_estacionamento": "espaco_publico",
    "patinete": "espaco_publico",
}
GROUPS = ("transito", "espaco_publico", "frota_e_outros")
GROUP_LABELS = {
    "transito": "equipamentos de trânsito",
    "espaco_publico": "equipamentos em espaço público",
    "frota_e_outros": "frota e outros",
}


def day_type(weekday: int) -> int:
    return _DAY_TYPE_OF_WEEKDAY[weekday]


def group_of(type_code: str) -> str:
    return TYPE_GROUPS.get(type_code, "frota_e_outros")


@dataclass(frozen=True, slots=True)
class Occurrence:
    at: datetime  # horário local, sem fuso
    region: str
    type_code: str


@dataclass(frozen=True, slots=True)
class Installation:
    region: str
    type_code: str
    installed_on: date


@dataclass(frozen=True, slots=True)
class EventWindow:
    kind: str
    region: str | None  # None = cidade toda
    starts_at: datetime  # local, sem fuso
    ends_at: datetime
    name: str = ""


@dataclass(slots=True)
class RiskModel:
    regions: tuple[str, ...]
    base: FloatArray  # [G] ocorrências por equipamento-hora
    region: FloatArray  # [R]
    hour: FloatArray  # [H]
    week: FloatArray  # [G, DAY_TYPES, BLOCKS]
    month: FloatArray  # [G, 12]
    event: FloatArray  # [G, len(EVENT_KINDS)]
    observed_events: int
    excluded_days: list[str] = field(default_factory=list)

    # ---- previsão -----------------------------------------------------------------------

    def rate(
        self, region_idx: int, group_idx: int, when: datetime, event_kind: int, exposure: float
    ) -> float:
        return float(
            exposure
            * self.base[group_idx]
            * self.region[region_idx]
            * self.hour[when.hour]
            * self.week[group_idx, day_type(when.weekday()), when.hour // BLOCK_HOURS]
            * self.month[group_idx, when.month - 1]
            * self.event[group_idx, event_kind]
        )

    def explain(
        self, region_idx: int, group_idx: int, when: datetime, event_kind: int
    ) -> list[dict[str, Any]]:
        """Fatores (com nome) que compõem a previsão de uma célula, do maior efeito ao menor."""
        block = when.hour // BLOCK_HOURS
        items = [
            (f"Região {self.regions[region_idx]}", self.region[region_idx]),
            (f"{when.hour:02d}h", self.hour[when.hour]),
            (
                f"{DAY_TYPES[day_type(when.weekday())]} {block * BLOCK_HOURS:02d}–"
                f"{block * BLOCK_HOURS + BLOCK_HOURS:02d}h ({GROUP_LABELS[GROUPS[group_idx]]})",
                self.week[group_idx, day_type(when.weekday()), block],
            ),
            (
                f"{MONTH_LABELS[when.month - 1]} ({GROUP_LABELS[GROUPS[group_idx]]})",
                self.month[group_idx, when.month - 1],
            ),
        ]
        if event_kind:
            items.append((f"Evento: {EVENT_KINDS[event_kind]}", self.event[group_idx, event_kind]))
        ranked = sorted(items, key=lambda item: abs(math.log(max(item[1], 1e-6))), reverse=True)
        return [{"factor": name, "multiplier": round(float(value), 2)} for name, value in ranked]

    def as_params(self) -> dict[str, Any]:
        return {
            "regions": list(self.regions),
            "groups": list(GROUPS),
            "base_per_device_hour": self.base.round(8).tolist(),
            "region": self.region.round(4).tolist(),
            "hour": self.hour.round(4).tolist(),
            "week": self.week.round(4).tolist(),
            "month": self.month.round(4).tolist(),
            "event": self.event.round(4).tolist(),
            "event_kinds": list(EVENT_KINDS),
            "observed_events": self.observed_events,
            "excluded_days": self.excluded_days,
        }

    @classmethod
    def from_params(cls, params: dict[str, Any]) -> RiskModel:
        return cls(
            regions=tuple(params["regions"]),
            base=np.asarray(params["base_per_device_hour"], dtype=np.float64),
            region=np.asarray(params["region"], dtype=np.float64),
            hour=np.asarray(params["hour"], dtype=np.float64),
            week=np.asarray(params["week"], dtype=np.float64),
            month=np.asarray(params["month"], dtype=np.float64),
            event=np.asarray(params["event"], dtype=np.float64),
            observed_events=int(params["observed_events"]),
            excluded_days=list(params.get("excluded_days", [])),
        )


# ---- montagem das matrizes ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Grid:
    """Cubo de células (R regiões × G grupos × D dias × 24 h) para ajuste e previsão."""

    regions: tuple[str, ...]
    days: tuple[date, ...]
    exposure: FloatArray  # [R, G, D] equipamentos instalados
    counts: FloatArray  # [R, G, D, H]
    events: NDArray[np.int64]  # [R, D, H] índice em EVENT_KINDS

    @property
    def weekday(self) -> NDArray[np.int64]:
        return np.asarray([day_type(d.weekday()) for d in self.days], dtype=np.int64)

    @property
    def month(self) -> NDArray[np.int64]:
        return np.asarray([d.month - 1 for d in self.days], dtype=np.int64)


def build_grid(
    regions: Sequence[str],
    start: date,
    end: date,
    installations: Iterable[Installation],
    occurrences: Iterable[Occurrence],
    events: Iterable[EventWindow],
    *,
    fixed_exposure: bool = False,
    type_weights: dict[str, float] | None = None,
    operating: Iterable[tuple[str, str, date, float]] | None = None,
) -> Grid:
    """``end`` exclusivo. Com ``fixed_exposure`` usa o parque atual em todos os dias (futuro).

    ``type_weights`` pondera a exposição pela taxa de falha relativa de cada tipo dentro do seu
    grupo (ver ``type_weights``): assim o fator de região mede o risco do lugar, não a mistura
    de tipos instalados nele (o Centro tem mais câmeras; o Norte, mais patinetes).
    """
    weights = type_weights or {}
    if operating is not None:  # exposição medida (equipamento-dias em operação)
        installations = []
    days = tuple(start + timedelta(days=i) for i in range((end - start).days))
    r_index = {code: i for i, code in enumerate(regions)}
    g_index = {g: i for i, g in enumerate(GROUPS)}
    d_index = {d: i for i, d in enumerate(days)}
    exposure = np.zeros((len(regions), len(GROUPS), len(days)))
    for inst in installations:
        r = r_index.get(inst.region)
        if r is None:
            continue
        g = g_index[group_of(inst.type_code)]
        weight = weights.get(inst.type_code, 1.0)
        if fixed_exposure or inst.installed_on <= start:
            exposure[r, g, :] += weight
        elif inst.installed_on < end:
            exposure[r, g, d_index[inst.installed_on] :] += weight
    for region, type_code, day, device_days in operating or []:
        r, d = r_index.get(region), d_index.get(day)
        if r is not None and d is not None:
            exposure[r, g_index[group_of(type_code)], d] += device_days * weights.get(
                type_code, 1.0
            )
    counts = np.zeros((len(regions), len(GROUPS), len(days), HOURS))
    for occ in occurrences:
        r, d = r_index.get(occ.region), d_index.get(occ.at.date())
        if r is None or d is None:
            continue
        counts[r, g_index[group_of(occ.type_code)], d, occ.at.hour] += 1
    event_cube = np.zeros((len(regions), len(days), HOURS), dtype=np.int64)
    for event in events:
        kind = EVENT_KINDS.index(event.kind) if event.kind in EVENT_KINDS else 0
        if not kind:
            continue
        moment = event.starts_at.replace(minute=0, second=0, microsecond=0)
        while moment < event.ends_at:
            d = d_index.get(moment.date())
            if d is not None:
                targets = (
                    range(len(regions)) if event.region is None else [r_index.get(event.region)]
                )
                for r in targets:
                    if r is not None:
                        event_cube[r, d, moment.hour] = max(event_cube[r, d, moment.hour], kind)
            moment += timedelta(hours=1)
    return Grid(tuple(regions), days, exposure, counts, event_cube)


def type_weights(
    operating: Iterable[tuple[str, str, date, float]],
    occurrences: Iterable[Occurrence],
    until: date,
) -> dict[str, float]:
    """Taxa de falha de cada tipo relativa à média do seu grupo (encolhida para 1)."""
    days: dict[str, float] = {}
    for _region, type_code, day, device_days in operating:
        if day < until:
            days[type_code] = days.get(type_code, 0.0) + device_days
    counts: dict[str, int] = {}
    for occ in occurrences:
        if occ.at.date() < until:
            counts[occ.type_code] = counts.get(occ.type_code, 0) + 1
    group_days: dict[str, float] = {}
    group_counts: dict[str, int] = {}
    for type_code, d in days.items():
        group = group_of(type_code)
        group_days[group] = group_days.get(group, 0.0) + d
        group_counts[group] = group_counts.get(group, 0) + counts.get(type_code, 0)
    weights: dict[str, float] = {}
    for type_code, d in days.items():
        group = group_of(type_code)
        group_rate = group_counts[group] / max(group_days[group], 1.0)
        if group_rate <= 0 or d <= 0:
            weights[type_code] = 1.0
            continue
        expected = group_rate * d
        weights[type_code] = (counts.get(type_code, 0) + SHRINK_EVENTS) / (expected + SHRINK_EVENTS)
    return weights


# ---- ajuste ------------------------------------------------------------------------------


def _expected(model: RiskModel, grid: Grid) -> FloatArray:
    weekday, month = grid.weekday, grid.month
    blocks = np.arange(HOURS) // BLOCK_HOURS
    lam = (
        grid.exposure[:, :, :, None]
        * model.base[None, :, None, None]
        * model.region[:, None, None, None]
        * model.hour[None, None, None, :]
    )
    lam = lam * model.week[:, weekday][:, :, blocks][None, :, :, :]
    lam = lam * model.month[:, month][None, :, :, None]
    lam = lam * np.transpose(model.event[:, grid.events], (1, 0, 2, 3))
    return np.asarray(lam, dtype=np.float64)


def _shrunk(
    observed: FloatArray, expected_at_one: FloatArray, strength: float = SHRINK_EVENTS
) -> FloatArray:
    return np.asarray((observed + strength) / (expected_at_one + strength))


def _drop_outlier_days(grid: Grid) -> tuple[Grid, list[str]]:
    """Dias com volume anômalo (ex.: a simulação ao vivo acelerada da demo) saem do treino."""
    per_day = grid.counts.sum(axis=(0, 1, 3))
    if per_day.size < 14:
        return grid, []
    limit = max(float(np.percentile(per_day, 99)) * 3.0, 10.0)
    keep = per_day <= limit
    if keep.all():
        return grid, []
    excluded = [grid.days[i].isoformat() for i in np.flatnonzero(~keep)]
    exposure = grid.exposure.copy()
    exposure[:, :, ~keep] = 0
    counts = grid.counts.copy()
    counts[:, :, ~keep, :] = 0
    return Grid(grid.regions, grid.days, exposure, counts, grid.events), excluded


def fit(grid: Grid, iterations: int = 40) -> RiskModel:
    grid, excluded = _drop_outlier_days(grid)
    n_regions = len(grid.regions)
    model = RiskModel(
        regions=grid.regions,
        base=np.full(len(GROUPS), 1e-4),
        region=np.ones(n_regions),
        hour=np.ones(HOURS),
        week=np.ones((len(GROUPS), len(DAY_TYPES), BLOCKS)),
        month=np.ones((len(GROUPS), 12)),
        event=np.ones((len(GROUPS), len(EVENT_KINDS))),
        observed_events=int(grid.counts.sum()),
        excluded_days=excluded,
    )
    counts = grid.counts
    month = grid.month
    week_block = (
        grid.weekday[:, None] * BLOCKS + (np.arange(HOURS) // BLOCK_HOURS)[None, :]
    ).ravel()
    for _ in range(iterations):
        # base por grupo (sem encolhimento: é o nível)
        lam = _expected(model, grid)
        obs_g, exp_g = counts.sum(axis=(0, 2, 3)), lam.sum(axis=(0, 2, 3))
        model.base *= np.where(exp_g > 0, (obs_g + 1e-9) / np.maximum(exp_g, 1e-12), 1.0)

        lam = _expected(model, grid)
        model.region = _shrunk(counts.sum(axis=(1, 2, 3)), lam.sum(axis=(1, 2, 3)) / model.region)

        lam = _expected(model, grid)
        model.hour = _shrunk(counts.sum(axis=(0, 1, 2)), lam.sum(axis=(0, 1, 2)) / model.hour)

        lam = _expected(model, grid)
        obs_w = _by_week_block(counts.sum(axis=0), week_block)
        exp_w = _by_week_block(lam.sum(axis=0), week_block)
        model.week = _shrunk(obs_w, exp_w / model.week, SHRINK_FINE_EVENTS)

        lam = _expected(model, grid)
        obs_m = _by_month(counts.sum(axis=(0, 3)), month)
        exp_m = _by_month(lam.sum(axis=(0, 3)), month)
        model.month = _shrunk(obs_m, exp_m / model.month, SHRINK_FINE_EVENTS)

        lam = _expected(model, grid)
        obs_e = np.zeros((len(GROUPS), len(EVENT_KINDS)))
        exp_e = np.zeros((len(GROUPS), len(EVENT_KINDS)))
        for kind in range(1, len(EVENT_KINDS)):
            mask = (grid.events == kind)[:, None, :, :]  # [R,1,D,H]
            obs_e[:, kind] = (counts * mask).sum(axis=(0, 2, 3))
            exp_e[:, kind] = (lam * mask).sum(axis=(0, 2, 3))
        updated = _shrunk(obs_e, exp_e / model.event)
        updated[:, 0] = 1.0
        model.event = updated

        _normalize(model, grid)
    return model


def _by_week_block(values: FloatArray, week_block: NDArray[np.int64]) -> FloatArray:
    """Soma [G, D, H] por (tipo de dia, faixa de horário) → [G, DAY_TYPES, BLOCKS]."""
    n = len(DAY_TYPES)
    return np.stack(
        [
            np.bincount(week_block, weights=values[g].ravel(), minlength=n * BLOCKS)
            for g in range(values.shape[0])
        ]
    ).reshape(values.shape[0], n, BLOCKS)


def _by_month(values: FloatArray, month: NDArray[np.int64]) -> FloatArray:
    """Soma [G, D] por mês → [G, 12]."""
    return np.stack(
        [np.bincount(month, weights=values[g], minlength=12) for g in range(values.shape[0])]
    )


def _normalize(model: RiskModel, grid: Grid) -> None:
    """Fatores com média 1 (ponderada pela exposição); o nível fica todo na ``base``."""
    lam = _expected(model, grid)
    total = lam.sum()
    for attr in ("region", "hour"):
        values = getattr(model, attr)
        mean = float(values.mean())
        setattr(model, attr, values / mean)
        model.base *= mean
    # A interação semana × faixa só guarda o que a hora não explica: média 1 por faixa,
    # entre os dias da semana (a forma do dia fica no fator de hora, que é interpretável).
    model.week = model.week / model.week.mean(axis=1, keepdims=True)
    for attr in ("week", "month"):
        values = getattr(model, attr)
        means = values.reshape(len(GROUPS), -1).mean(axis=1)
        setattr(model, attr, values / means.reshape((len(GROUPS),) + (1,) * (values.ndim - 1)))
        model.base *= means
    if total > 0:  # corrige o nível após a renormalização
        model.base *= total / max(_expected(model, grid).sum(), 1e-12)


def expected_cube(model: RiskModel, grid: Grid) -> FloatArray:
    """λ por célula [R, G, D, H] (útil para previsão e backtest)."""
    return _expected(model, grid)
