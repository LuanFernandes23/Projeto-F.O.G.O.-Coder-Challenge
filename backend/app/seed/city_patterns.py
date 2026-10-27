"""Padrões "verdadeiros" da cidade simulada (usados SÓ pelo seed e pelo simulador).

Estes multiplicadores definem quando as ocorrências acontecem na simulação: hora do dia,
dia da semana, estação do ano e eventos do calendário. O motor preditivo
(``app.domain.prediction``) **não lê este módulo**: ele recebe apenas o histórico de
ocorrências e o calendário público de eventos (tabela ``city_events``) e precisa
redescobrir os padrões; o backtest mede se conseguiu. Um teste garante essa separação.
"""

import hashlib
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta

# Peso por hora do dia (0-23): falhas e vandalismo concentrados no fim da tarde e à noite.
HOUR_WEIGHTS: tuple[float, ...] = (
    3, 2, 2, 1, 1, 1, 1, 2, 3, 3, 3, 3, 3, 3, 4, 4, 4, 5, 6, 7, 7, 6, 5, 4,
)  # fmt: skip
_HOUR_MEAN = sum(HOUR_WEIGHTS) / 24

TRAFFIC_TYPES = frozenset({"semaforo", "radar", "cancela"})
VANDALISM_TYPES = frozenset({"camera", "totem_estacionamento", "patinete"})
WEATHER_SENSITIVE_TYPES = frozenset({"semaforo", "camera", "radar"})


@dataclass(frozen=True, slots=True)
class CityEvent:
    """Evento público do calendário (o tipo de informação que a prefeitura já conhece)."""

    name: str
    kind: str  # feriado | esporte | cultura | feira
    region_code: str | None  # None = cidade inteira
    starts_at: datetime  # horário local (sem fuso: interpretado no fuso da cidade)
    ends_at: datetime
    expected_public: int


def hour_factor(hour: int) -> float:
    return HOUR_WEIGHTS[hour] / _HOUR_MEAN


def weekday_factor(type_code: str, when: datetime) -> float:
    """Pico de trânsito nos dias úteis; vandalismo nas noites de sexta e sábado."""
    weekday, hour = when.weekday(), when.hour
    factor = 1.0
    if type_code in TRAFFIC_TYPES:
        if weekday < 5 and (7 <= hour <= 9 or 17 <= hour <= 19):
            factor *= 1.7
        elif weekday >= 5:
            factor *= 0.75
    if type_code in VANDALISM_TYPES:
        friday_night = weekday == 4 and hour >= 20
        saturday_night = weekday == 5 and (hour >= 20 or hour <= 3)
        sunday_dawn = weekday == 6 and hour <= 3
        if friday_night or saturday_night or sunday_dawn:
            factor *= 2.2
    return factor


def season_factor(type_code: str, day: date) -> float:
    """Estação chuvosa (dez-mar) castiga semáforos, câmeras e radares; inverno seco alivia."""
    if type_code not in WEATHER_SENSITIVE_TYPES:
        return 1.0
    if day.month in (12, 1, 2, 3):
        return 1.45
    if day.month in (6, 7, 8):
        return 0.85
    return 1.0


def event_factor(
    type_code: str, region_code: str, when: datetime, events: list[CityEvent]
) -> float:
    factor = 1.0
    for event in events:
        if not event.starts_at <= when < event.ends_at:
            continue
        if event.region_code not in (None, region_code):
            continue
        if event.kind == "feriado":
            # Menos trânsito, mais vandalismo e furto.
            factor *= 0.8 if type_code in TRAFFIC_TYPES else 1.35
        else:
            factor *= 1.0 + min(event.expected_public / 10_000, 2.0)
    return factor


def intensity(type_code: str, region_code: str, when: datetime, events: list[CityEvent]) -> float:
    """Multiplicador total (média ≈ 1) aplicado à taxa base de falhas do equipamento."""
    return (
        hour_factor(when.hour)
        * weekday_factor(type_code, when)
        * season_factor(type_code, when.date())
        * event_factor(type_code, region_code, when, events)
    )


# Limite superior do multiplicador, usado no "thinning" (Lewis-Shedler) do seed.
MAX_INTENSITY = max(HOUR_WEIGHTS) / _HOUR_MEAN * 2.2 * 1.45 * 3.0


_FIXED_HOLIDAYS = (
    (1, 1, "Confraternização Universal"),
    (4, 4, "Aniversário de Marília"),
    (4, 21, "Tiradentes"),
    (5, 1, "Dia do Trabalho"),
    (9, 7, "Independência do Brasil"),
    (10, 12, "Nossa Senhora Aparecida"),
    (11, 2, "Finados"),
    (11, 15, "Proclamação da República"),
    (11, 20, "Dia da Consciência Negra"),
    (12, 25, "Natal"),
)
_MOVABLE_HOLIDAYS = {
    2025: ((3, 3, "Carnaval"), (3, 4, "Carnaval"), (4, 18, "Sexta-feira Santa"),
           (6, 19, "Corpus Christi")),
    2026: ((2, 16, "Carnaval"), (2, 17, "Carnaval"), (4, 3, "Sexta-feira Santa"),
           (6, 4, "Corpus Christi")),
    2027: ((2, 8, "Carnaval"), (2, 9, "Carnaval"), (3, 26, "Sexta-feira Santa"),
           (5, 27, "Corpus Christi")),
}  # fmt: skip


def build_calendar(start: date, end: date) -> list[CityEvent]:
    """Calendário público de Marília entre ``start`` e ``end`` (feriados e eventos recorrentes).

    Os eventos são fictícios, mas plausíveis: jogos do MAC no estádio (Leste), feira noturna
    do Centro, shows no recinto de exposições (Norte) e festas de bairro (Sul).
    """
    events: list[CityEvent] = []
    for year in range(start.year, end.year + 1):
        holidays = [(m, d, n) for m, d, n in _FIXED_HOLIDAYS]
        holidays += list(_MOVABLE_HOLIDAYS.get(year, ()))
        for month, day_of_month, name in holidays:
            when = date(year, month, day_of_month)
            if start <= when <= end:
                begin = datetime(when.year, when.month, when.day)
                events.append(CityEvent(name, "feriado", None, begin, begin + timedelta(days=1), 0))
    day = start
    while day <= end:
        midnight = datetime(day.year, day.month, day.day)
        iso_week = day.isocalendar().week
        if day.weekday() == 6 and iso_week % 2 == 0 and day.month not in (12, 1):
            events.append(
                CityEvent(
                    "Jogo do MAC no Estádio Bento de Abreu",
                    "esporte",
                    "leste",
                    midnight + timedelta(hours=15),
                    midnight + timedelta(hours=20),
                    12_000,
                )
            )
        if day.weekday() == 3:
            events.append(
                CityEvent(
                    "Feira noturna da Praça Saturnino de Brito",
                    "feira",
                    "centro",
                    midnight + timedelta(hours=18),
                    midnight + timedelta(hours=23),
                    5_000,
                )
            )
        if day.weekday() == 5 and day.day <= 7:
            events.append(
                CityEvent(
                    "Show no Recinto de Exposições",
                    "cultura",
                    "norte",
                    midnight + timedelta(hours=20),
                    midnight + timedelta(hours=26),
                    15_000,
                )
            )
        if day.weekday() == 5 and 15 <= day.day <= 21:
            events.append(
                CityEvent(
                    "Festa de bairro na Zona Sul",
                    "cultura",
                    "sul",
                    midnight + timedelta(hours=17),
                    midnight + timedelta(hours=23),
                    4_000,
                )
            )
        day += timedelta(days=1)
    return events


def device_baseline(equipment_id: str) -> tuple[float, float]:
    """Sinal (dBm) e uptime (%) típicos de cada equipamento, estáveis entre seed e simulador."""
    digest = hashlib.sha256(equipment_id.encode()).digest()
    signal = -85 + 25 * digest[0] / 255
    uptime = 99.2 + 0.7 * digest[1] / 255
    return round(signal, 1), round(uptime, 2)


def expected_temperature(local_hour: float) -> float:
    """Temperatura do invólucro ao longo do dia (sem defeito)."""
    return 27 + 9 * math.sin((local_hour - 9) / 24 * 2 * math.pi)
