"""Clocks. The demo compresses a care day into a few minutes; production uses wall time."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone


class WallClock:
    speed = 1.0

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class SimClock:
    """Simulated time: ``start`` at the moment of creation, advancing ``speed``× real time."""

    def __init__(self, start: datetime, speed: float = 60.0) -> None:
        self._start = start
        self._real0 = time.monotonic()
        self.speed = speed
        self._paused_at: datetime | None = None

    def now(self) -> datetime:
        if self._paused_at is not None:
            return self._paused_at
        return self._start + timedelta(seconds=(time.monotonic() - self._real0) * self.speed)

    def set(self, at: datetime, speed: float | None = None) -> None:
        self._start = at
        self._real0 = time.monotonic()
        if speed is not None:
            self.speed = speed
        self._paused_at = None

    def pause(self) -> None:
        self._paused_at = self.now()

    def resume(self) -> None:
        if self._paused_at is not None:
            self.set(self._paused_at)
