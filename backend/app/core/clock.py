"""Relógio injetável: permite testes determinísticos e a simulação histórica do seed."""

from datetime import UTC, date, datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo


class Clock(Protocol):
    def now(self) -> datetime: ...

    def today(self) -> date: ...


class SystemClock:
    def __init__(self, tz: ZoneInfo) -> None:
        self._tz = tz

    def now(self) -> datetime:
        return datetime.now(UTC)

    def today(self) -> date:
        return datetime.now(self._tz).date()


class ManualClock:
    """Relógio controlado manualmente (testes e simulação do seed)."""

    def __init__(self, start: datetime, tz: ZoneInfo) -> None:
        if start.tzinfo is None:
            raise ValueError("ManualClock exige datetime com timezone")
        self._now = start
        self._tz = tz

    def now(self) -> datetime:
        return self._now

    def today(self) -> date:
        return self._now.astimezone(self._tz).date()

    def set(self, moment: datetime) -> None:
        self._now = moment

    def advance(self, delta: timedelta) -> None:
        self._now += delta
