"""Ambient temperature at the household (Open-Meteo, free, no API key)."""

from __future__ import annotations

import time
from datetime import datetime

import httpx

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"


class AmbientTemperature:
    """Callable ``(datetime) -> °C`` with a small cache; falls back to a fixed value offline."""

    def __init__(self, lat: float, lon: float, *, fallback_c: float = 30.0, ttl_s: float = 600,
                 override_c: float | None = None) -> None:
        self.lat, self.lon = lat, lon
        self.fallback_c = fallback_c
        self.override_c = override_c  # demo mode: force a hot afternoon
        self.ttl_s = ttl_s
        self._cached: tuple[float, float] | None = None  # (fetched_at, value)
        self.last_source = "fallback"

    def current(self) -> float:
        if self.override_c is not None:
            self.last_source = "override"
            return self.override_c
        if self._cached and time.time() - self._cached[0] < self.ttl_s:
            return self._cached[1]
        try:
            r = httpx.get(OPEN_METEO, params={"latitude": self.lat, "longitude": self.lon,
                                              "current": "temperature_2m"}, timeout=8)
            r.raise_for_status()
            value = float(r.json()["current"]["temperature_2m"])
            self._cached = (time.time(), value)
            self.last_source = "open-meteo"
            return value
        except (httpx.HTTPError, KeyError, ValueError):
            self.last_source = "fallback"
            return self.fallback_c

    def __call__(self, _at: datetime | None = None) -> float:
        return self.current()
