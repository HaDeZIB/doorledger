"""Thermal exposure model for a medication package sitting on a porch.

We cannot put a thermometer in the box, so we estimate. A shipped cold pack behaves roughly
like a lumped body warming toward ambient (Newton's law of heating):

    T(t) = T_amb + (T0 - T_amb) * exp(-t / tau)

``tau`` (minutes) captures insulation + ice packs. Typical insulated pharmacy mailers keep
contents cold for hours when shaded; direct sun on a dark porch shortens that a lot, so sun
exposure lowers tau. These are deliberately conservative, documented assumptions — the point
is an *early warning with evidence*, not a lab measurement.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from .domain import MedicationProfile

DEFAULT_TAU_MIN = 90.0  # insulated mailer, shaded
SUN_TAU_FACTOR = 0.5  # direct sun roughly halves the time constant


@dataclass
class ExposureEstimate:
    minutes_on_porch: float
    ambient_c: float
    estimated_internal_c: float
    minutes_above_store_max: float
    minutes_until_store_max: float | None  # None = already above / never reaches
    minutes_until_excursion_max: float | None  # minutes until the relevant unsafe limit
    status: str  # safe | at_risk | compromised
    direction: str | None = None  # "hot" (heading to excursion_max) | "cold" (heading to freezing)
    unsafe_c: float | None = None  # the limit being approached

    def as_dict(self) -> dict[str, float | str | None]:
        return self.__dict__.copy()


def _temp(t_min: float, t0: float, ambient: float, tau: float) -> float:
    return ambient + (t0 - ambient) * math.exp(-t_min / tau)


def _time_to(threshold: float, t0: float, ambient: float, tau: float) -> float | None:
    """Minutes from drop-off until internal temperature reaches ``threshold`` (warming)."""
    if ambient <= threshold:
        return None  # never reaches it
    if t0 >= threshold:
        return 0.0
    return -tau * math.log((threshold - ambient) / (t0 - ambient))


def _time_to_cold(threshold: float, t0: float, ambient: float, tau: float) -> float | None:
    """Minutes until internal temperature falls to ``threshold`` (cooling toward a cold porch)."""
    if ambient >= threshold:
        return None
    if t0 <= threshold:
        return 0.0
    return -tau * math.log((threshold - ambient) / (t0 - ambient))


def estimate(
    dropped_at: datetime,
    now: datetime,
    ambient_c: float,
    profile: MedicationProfile | None = None,
    *,
    initial_c: float = 5.0,
    in_sun: bool = False,
    tau_min: float = DEFAULT_TAU_MIN,
    at_risk_window_min: float = 20.0,
) -> ExposureEstimate:
    profile = profile or MedicationProfile()
    tau = tau_min * (SUN_TAU_FACTOR if in_sun else 1.0)
    elapsed = max((now - dropped_at).total_seconds() / 60.0, 0.0)
    internal = _temp(elapsed, initial_c, ambient_c, tau)

    t_store = _time_to(profile.store_max_c, initial_c, ambient_c, tau)
    t_exc = _time_to(profile.excursion_max_c, initial_c, ambient_c, tau)
    above_store = max(elapsed - t_store, 0.0) if t_store is not None else 0.0

    until_store = None if t_store is None else max(t_store - elapsed, 0.0)
    until_exc = None if t_exc is None else max(t_exc - elapsed, 0.0)

    # Cold side: insulin must never freeze (frozen insulin has to be thrown away).
    t_freeze = _time_to_cold(profile.freeze_c, initial_c, ambient_c, tau)
    until_freeze = None if t_freeze is None else max(t_freeze - elapsed, 0.0)
    direction = "cold" if ambient_c < profile.store_min_c else ("hot" if ambient_c > profile.store_max_c
                                                                  else None)

    cap = profile.max_minutes_above_store
    compromised = (internal >= profile.excursion_max_c or internal <= profile.freeze_c
                   or (cap is not None and above_store >= cap))
    if compromised:
        status = "compromised"
    else:
        budget_left = (cap - above_store) if (cap is not None and t_store is not None) else None
        soonest = min(x for x in (until_exc, until_freeze, budget_left, math.inf) if x is not None)
        status = "at_risk" if soonest <= at_risk_window_min else "safe"
    if direction == "cold":
        until_exc, unsafe = until_freeze, profile.freeze_c
    else:
        unsafe = profile.excursion_max_c if direction == "hot" else None

    return ExposureEstimate(
        minutes_on_porch=round(elapsed, 1),
        ambient_c=ambient_c,
        estimated_internal_c=round(internal, 1),
        minutes_above_store_max=round(above_store, 1),
        minutes_until_store_max=None if until_store is None else round(until_store, 1),
        minutes_until_excursion_max=None if until_exc is None else round(until_exc, 1),
        status=status,
        direction=direction,
        unsafe_c=unsafe,
    )


def deadline(
    dropped_at: datetime,
    ambient_c: float,
    profile: MedicationProfile | None = None,
    *,
    initial_c: float = 5.0,
    in_sun: bool = False,
    tau_min: float = DEFAULT_TAU_MIN,
) -> datetime | None:
    """Wall-clock time by which the package should be brought inside (None = no deadline)."""
    profile = profile or MedicationProfile()
    tau = tau_min * (SUN_TAU_FACTOR if in_sun else 1.0)
    t_store = _time_to(profile.store_max_c, initial_c, ambient_c, tau)
    t_exc = _time_to(profile.excursion_max_c, initial_c, ambient_c, tau)
    t_freeze = _time_to_cold(profile.freeze_c, initial_c, ambient_c, tau)
    candidates = [] if t_freeze is None else [t_freeze]
    if t_store is not None and profile.max_minutes_above_store is not None:
        candidates.append(t_store + profile.max_minutes_above_store)
    if t_exc is not None:
        candidates.append(t_exc)
    if not candidates:
        return None
    return dropped_at + timedelta(minutes=min(candidates))
