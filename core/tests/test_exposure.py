"""Thermal exposure model (Newton heating/cooling) checked against hand-computed values.

T(t) = T_amb + (T0 - T_amb) * exp(-t / tau), T0 = 5 °C, tau = 90 min shaded (45 in sun).
Time to reach a threshold X:  t = -tau * ln((X - T_amb) / (T0 - T_amb)).
"""

from datetime import UTC, datetime, timedelta

import pytest
from doorledger import exposure
from doorledger.domain import MedicationProfile

T0 = datetime(2026, 10, 11, 14, 0, tzinfo=UTC)


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


# ------------------------------------------------------------------ hot porch (35 °C)
# t_store  = -90 ln((8-35)/(5-35))  = 90 ln(30/27) =   9.4824 min
# t_exc    = -90 ln((30-35)/(5-35)) = 90 ln 6      = 161.2589 min
# T(60)    = 35 - 30 e^(-60/90)     = 19.5975 °C


def test_hot_direction_matches_hand_computed_values():
    e = exposure.estimate(T0, at(60), 35.0)
    assert e.direction == "hot"
    assert e.unsafe_c == 30.0
    assert e.minutes_on_porch == 60.0
    assert e.estimated_internal_c == pytest.approx(19.6, abs=0.05)
    assert e.minutes_above_store_max == pytest.approx(60 - 9.4824, abs=0.05)
    assert e.minutes_until_store_max == 0.0
    assert e.minutes_until_excursion_max == pytest.approx(161.2589 - 60, abs=0.05)
    assert e.status == "safe"


def test_hot_before_store_max_reports_time_left():
    e = exposure.estimate(T0, at(5), 35.0)
    assert e.minutes_until_store_max == pytest.approx(9.4824 - 5, abs=0.05)
    assert e.minutes_above_store_max == 0.0


def test_hot_at_risk_then_compromised():
    # 145 min: 16.3 min to 30 °C -> inside the 20 min at-risk window
    risk = exposure.estimate(T0, at(145), 35.0)
    assert risk.status == "at_risk"
    assert risk.minutes_until_excursion_max == pytest.approx(16.26, abs=0.05)
    # 170 min: T = 35 - 30 e^(-170/90) = 30.46 °C >= excursion_max
    bad = exposure.estimate(T0, at(170), 35.0)
    assert bad.status == "compromised"
    assert bad.estimated_internal_c == pytest.approx(30.5, abs=0.05)


def test_sun_halves_tau():
    shade = exposure.deadline(T0, 35.0)
    sun = exposure.deadline(T0, 35.0, in_sun=True)
    assert (shade - T0).total_seconds() / 60 == pytest.approx(161.2589, abs=0.01)
    assert (sun - T0).total_seconds() / 60 == pytest.approx(80.6294, abs=0.01)
    # T(60) in sun = 35 - 30 e^(-60/45) = 27.09 °C
    assert exposure.estimate(T0, at(60), 35.0, in_sun=True).estimated_internal_c == pytest.approx(
        27.1, abs=0.05)


def test_at_risk_window_is_configurable():
    assert exposure.estimate(T0, at(145), 35.0, at_risk_window_min=10).status == "safe"
    assert exposure.estimate(T0, at(145), 35.0, at_risk_window_min=20).status == "at_risk"


# ------------------------------------------------------------------ cold porch (-9 °C)
# t_freeze = -90 ln((0+9)/(5+9)) = 90 ln(14/9) = 39.7650 min
# T(30) = -9 + 14 e^(-1/3) = 1.0314 °C ; T(45) = -9 + 14 e^(-1/2) = -0.5086 °C


def test_cold_direction_matches_hand_computed_values():
    e = exposure.estimate(T0, at(30), -9.0)
    assert e.direction == "cold"
    assert e.unsafe_c == 0.0
    assert e.estimated_internal_c == pytest.approx(1.0, abs=0.05)
    # on the cold side "minutes until excursion" is the time until freezing
    assert e.minutes_until_excursion_max == pytest.approx(39.765 - 30, abs=0.05)
    assert e.minutes_until_store_max is None  # never warms to 8 °C on a -9 °C porch
    assert e.minutes_above_store_max == 0.0
    assert e.status == "at_risk"


def test_cold_safe_early():
    e = exposure.estimate(T0, at(10), -9.0)
    assert e.status == "safe"
    assert e.minutes_until_excursion_max == pytest.approx(29.765, abs=0.05)


def test_freeze_is_compromise():
    e = exposure.estimate(T0, at(45), -9.0)
    assert e.estimated_internal_c == pytest.approx(-0.5, abs=0.05)
    assert e.status == "compromised"


def test_cold_deadline_is_time_to_freeze():
    d = exposure.deadline(T0, -9.0)
    assert (d - T0).total_seconds() / 60 == pytest.approx(39.765, abs=0.01)


# ------------------------------------------------------------------ strict profiles


STRICT = MedicationProfile(name="Biologic", max_minutes_above_store=30)
# ambient 25 °C: never reaches 30 °C, t_store = 90 ln(20/17) = 14.6267 min


def test_max_minutes_above_store_deadline():
    d = exposure.deadline(T0, 25.0, STRICT)
    assert (d - T0).total_seconds() / 60 == pytest.approx(14.6267 + 30, abs=0.01)
    # the same porch is fine for plain insulin (no cap, never reaches 30 °C)
    assert exposure.deadline(T0, 25.0) is None


def test_max_minutes_above_store_status_progression():
    assert exposure.estimate(T0, at(20), 25.0, STRICT).status == "safe"  # 24.6 min budget left
    mid = exposure.estimate(T0, at(30), 25.0, STRICT)
    assert mid.status == "at_risk"  # 14.6 min budget left
    assert mid.minutes_above_store_max == pytest.approx(30 - 14.6267, abs=0.05)
    assert exposure.estimate(T0, at(45), 25.0, STRICT).status == "compromised"


def test_strict_status_consistent_with_deadline():
    profile = MedicationProfile(name="Biologic", max_minutes_above_store=15)
    d = exposure.deadline(T0, 25.0, profile)
    assert (d - T0).total_seconds() / 60 == pytest.approx(14.6267 + 15, abs=0.01)
    e = exposure.estimate(T0, at(1), 25.0, profile)
    assert e.estimated_internal_c < 8.0  # still within fridge range
    assert e.status == "safe"  # 28.6 min until the deadline > 20 min at-risk window


# ------------------------------------------------------------------ edge cases


def test_no_deadline_when_ambient_within_fridge_range():
    assert exposure.deadline(T0, 5.0) is None
    e = exposure.estimate(T0, at(600), 5.0)
    assert e.status == "safe"
    assert e.direction is None and e.unsafe_c is None
    assert e.minutes_until_store_max is None
    assert e.minutes_until_excursion_max is None
    assert e.estimated_internal_c == 5.0


def test_now_before_drop_clamps_to_zero():
    e = exposure.estimate(T0, T0 - timedelta(minutes=5), 35.0)
    assert e.minutes_on_porch == 0.0
    assert e.estimated_internal_c == 5.0


def test_as_dict_round_trip():
    e = exposure.estimate(T0, at(30), -9.0)
    d = e.as_dict()
    assert d["status"] == "at_risk" and d["direction"] == "cold" and d["ambient_c"] == -9.0
