"""Deterministic reconciliation: expected care vs. observed door events -> findings."""

from datetime import UTC, datetime

import pytest
from doorledger.domain import (
    Expectation,
    ExpectationKind,
    FindingKind,
    MedicationProfile,
    Observation,
    ObservationKind,
    Severity,
    Source,
)
from doorledger.reconcile import reconcile

DAY = datetime(2026, 10, 11, tzinfo=UTC)
VID = "V-MORNING"


def t(hh: int, mm: int = 0) -> datetime:
    return DAY.replace(hour=hh, minute=mm)


def visit(planned: int = 120, visit_id: str = VID) -> Expectation:
    return Expectation(ExpectationKind.CAREGIVER_VISIT, "Morning care", t(9), t(11),
                       caregiver="Maria", planned_minutes=planned, visit_id=visit_id)


def delivery(start: int = 13, end: int = 17, title: str = "Insulin") -> Expectation:
    return Expectation(ExpectationKind.MEDICATION_DELIVERY, title, t(start), t(end),
                       medication=MedicationProfile())


def obs(kind: ObservationKind, when: datetime, visit_id: str | None = None) -> Observation:
    return Observation(kind, when, Source.SIMULATED, visit_id=visit_id)


def check_in(when: datetime, visit_id: str = VID) -> Observation:
    return obs(ObservationKind.PRESENCE_CHECK_IN, when, visit_id)


def check_out(when: datetime, visit_id: str = VID) -> Observation:
    return obs(ObservationKind.PRESENCE_CHECK_OUT, when, visit_id)


def kinds(r) -> list[tuple[FindingKind, Severity]]:
    return [(f.kind, f.severity) for f in r.findings]


# ------------------------------------------------------------------ visits


def test_no_findings_before_grace():
    assert reconcile([visit()], [], t(9, 10)).findings == []


def test_on_time_check_in():
    ci = check_in(t(9, 10))
    r = reconcile([visit()], [ci], t(9, 30))
    assert kinds(r) == [(FindingKind.ON_TIME, Severity.INFO)]
    assert r.findings[0].observation_ids == [ci.id]
    assert r.visits[0].check_in is ci


def test_early_check_in_within_30_min_counts():
    r = reconcile([visit()], [check_in(t(8, 40))], t(9, 0))
    assert kinds(r) == [(FindingKind.ON_TIME, Severity.INFO)]


def test_check_in_before_window_minus_30_is_ignored():
    r = reconcile([visit()], [check_in(t(8, 20))], t(9, 20))
    assert r.visits[0].check_in is None
    assert kinds(r) == [(FindingKind.LATE_ARRIVAL, Severity.WARNING)]


def test_late_warning_before_arrival():
    r = reconcile([visit()], [], t(9, 20))
    assert kinds(r) == [(FindingKind.LATE_ARRIVAL, Severity.WARNING)]
    assert r.findings[0].needs_action


def test_exactly_45_min_is_still_late_not_missed():
    r = reconcile([visit()], [], t(9, 45))
    assert kinds(r) == [(FindingKind.LATE_ARRIVAL, Severity.WARNING)]


def test_missed_after_45_min():
    r = reconcile([visit()], [], t(9, 46))
    assert kinds(r) == [(FindingKind.MISSED_VISIT, Severity.CRITICAL)]
    assert "46 min" in r.findings[0].summary


def test_late_info_after_arrival():
    ci = check_in(t(9, 22))
    r = reconcile([visit()], [ci], t(9, 30))
    assert kinds(r) == [(FindingKind.LATE_ARRIVAL, Severity.INFO)]
    f = r.findings[0]
    assert f.data == {"late_minutes": 22}
    assert f.at == ci.at
    assert not f.needs_action


def test_short_visit():
    r = reconcile([visit()], [check_in(t(9, 22)), check_out(t(10, 5))], t(10, 20))
    assert kinds(r) == [(FindingKind.LATE_ARRIVAL, Severity.INFO),
                        (FindingKind.SHORT_VISIT, Severity.WARNING)]
    assert r.findings[1].data == {"minutes_on_site": 43, "planned_minutes": 120}
    assert r.visits[0].minutes_on_site == pytest.approx(43)


def test_visit_at_75_percent_is_completed():
    # 90 of 120 planned minutes is exactly the 75 % threshold -> not short
    r = reconcile([visit()], [check_in(t(9)), check_out(t(10, 30))], t(11))
    assert kinds(r) == [(FindingKind.ON_TIME, Severity.INFO),
                        (FindingKind.VISIT_COMPLETED, Severity.INFO)]
    assert r.findings[1].data["minutes_on_site"] == 90


def test_check_out_before_check_in_is_ignored():
    r = reconcile([visit()], [check_out(t(8, 50)), check_in(t(9, 5))], t(9, 30))
    assert r.visits[0].check_out is None
    assert kinds(r) == [(FindingKind.ON_TIME, Severity.INFO)]


def test_other_visit_ids_do_not_count():
    r = reconcile([visit()], [check_in(t(9, 5), "V-OTHER")], t(9, 20))
    assert kinds(r) == [(FindingKind.LATE_ARRIVAL, Severity.WARNING)]


def test_future_observations_ignored():
    # check-in stamped 9:30 while "now" is 9:20 (e.g. a replay running ahead)
    r = reconcile([visit()], [check_in(t(9, 30))], t(9, 20))
    assert r.visits[0].check_in is None
    assert kinds(r) == [(FindingKind.LATE_ARRIVAL, Severity.WARNING)]


def test_observation_order_does_not_matter():
    ci, co = check_in(t(9, 5)), check_out(t(11, 5))
    a = reconcile([visit()], [ci, co], t(11, 10))
    b = reconcile([visit()], [co, ci], t(11, 10))
    assert kinds(a) == kinds(b) == [(FindingKind.ON_TIME, Severity.INFO),
                                    (FindingKind.VISIT_COMPLETED, Severity.INFO)]


# ------------------------------------------------------------------ deliveries


def drop(when: datetime) -> Observation:
    return obs(ObservationKind.PACKAGE_DROPPED, when)


def removed(when: datetime) -> Observation:
    return obs(ObservationKind.PACKAGE_REMOVED, when)


def test_delivered_on_mild_day_is_exposed_info():
    d = drop(t(14))
    r = reconcile([delivery()], [d], t(14, 5), ambient_c=20.0)
    assert kinds(r) == [(FindingKind.PACKAGE_EXPOSED, Severity.INFO)]
    f = r.findings[0]
    assert f.at == d.at and f.observation_ids == [d.id]
    assert f.data["ambient_c"] == 20.0 and f.data["status"] == "safe"


@pytest.mark.parametrize("when,matched", [
    ((11, 59), False),  # more than 60 min before window_start
    ((12, 0), True),
    ((20, 0), True),    # window_end + 180 min
    ((20, 1), False),
])
def test_drop_match_window(when, matched):
    r = reconcile([delivery()], [drop(t(*when))], t(21), ambient_c=5.0)
    assert (r.deliveries[0].dropped is not None) is matched


def test_overdue():
    assert reconcile([delivery()], [], t(18)).findings == []  # exactly window_end + 60
    r = reconcile([delivery()], [], t(18, 1))
    assert kinds(r) == [(FindingKind.DELIVERY_OVERDUE, Severity.WARNING)]


def test_at_risk_on_cold_porch():
    # -9 °C: 9.8 min until freezing after 30 min outside
    r = reconcile([delivery()], [drop(t(14))], t(14, 30), ambient_c=-9.0)
    assert kinds(r) == [(FindingKind.PACKAGE_AT_RISK, Severity.WARNING)]
    assert r.findings[0].data["direction"] == "cold"


def test_compromised_cold_mentions_freezing():
    r = reconcile([delivery()], [drop(t(14))], t(14, 45), ambient_c=-9.0)
    assert kinds(r) == [(FindingKind.PACKAGE_COMPROMISED, Severity.CRITICAL)]
    assert "frozen" in r.findings[0].summary


def test_compromised_hot_does_not_mention_freezing():
    r = reconcile([delivery()], [drop(t(14))], t(17), ambient_c=35.0)
    assert kinds(r) == [(FindingKind.PACKAGE_COMPROMISED, Severity.CRITICAL)]
    assert "frozen" not in r.findings[0].summary


def test_retrieved_before_limit_is_safe_info():
    d, rm = drop(t(14)), removed(t(14, 33))
    # 33 min at -9 °C is inside the at-risk window, but it made it inside in time
    r = reconcile([delivery()], [d, rm], t(15), ambient_c=-9.0)
    assert kinds(r) == [(FindingKind.PACKAGE_RETRIEVED, Severity.INFO)]
    f = r.findings[0]
    assert f.data["status"] == "safe"
    assert f.data["minutes_on_porch"] == 33.0
    assert f.observation_ids == [d.id, rm.id]
    assert f.at == rm.at


def test_retrieved_after_limit_is_critical():
    r = reconcile([delivery()], [drop(t(14)), removed(t(14, 50))], t(15), ambient_c=-9.0)
    assert kinds(r) == [(FindingKind.PACKAGE_RETRIEVED, Severity.CRITICAL)]
    assert r.findings[0].data["status"] == "compromised"


def test_exposure_frozen_at_removal_time():
    """Once inside, time stops counting even if 'now' is much later."""
    r = reconcile([delivery()], [drop(t(14)), removed(t(14, 10))], t(23), ambient_c=-9.0)
    assert r.deliveries[0].estimate.minutes_on_porch == 10.0


def test_ambient_callable_is_evaluated_at_end():
    seen = []

    def ambient(when):
        seen.append(when)
        return -9.0

    reconcile([delivery()], [drop(t(14))], t(14, 30), ambient_c=ambient)
    assert seen == [t(14, 30)]


def test_multiple_deliveries_do_not_steal_each_others_drops():
    morning = delivery(9, 10, "Morning refill")
    afternoon = delivery(13, 14, "Afternoon refill")
    d1, r1, d2 = drop(t(9, 30)), removed(t(9, 45)), drop(t(13, 30))
    r = reconcile([afternoon, morning], [d2, r1, d1], t(13, 35), ambient_c=20.0)
    by_title = {d.expectation.title: d for d in r.deliveries}
    assert by_title["Morning refill"].dropped is d1
    assert by_title["Morning refill"].removed is r1
    assert by_title["Afternoon refill"].dropped is d2
    assert by_title["Afternoon refill"].removed is None
    assert kinds(r) == [(FindingKind.PACKAGE_RETRIEVED, Severity.INFO),
                        (FindingKind.PACKAGE_EXPOSED, Severity.INFO)]


def test_second_delivery_without_drop_goes_overdue():
    morning = delivery(9, 10, "Morning refill")
    afternoon = delivery(13, 14, "Afternoon refill")
    r = reconcile([morning, afternoon], [drop(t(9, 30))], t(15, 1), ambient_c=5.0)
    assert [(f.kind, f.expectation_id) for f in r.findings] == [
        (FindingKind.PACKAGE_EXPOSED, morning.id),
        (FindingKind.DELIVERY_OVERDUE, afternoon.id),
    ]


def test_ambiguous_drop_goes_to_nearest_window():
    morning = delivery(9, 10, "Morning refill")
    afternoon = delivery(13, 14, "Afternoon refill")
    d = drop(t(12, 30))
    r = reconcile([morning, afternoon], [d], t(15, 1), ambient_c=5.0)
    by_title = {x.expectation.title: x for x in r.deliveries}
    assert by_title["Afternoon refill"].dropped is d


def test_visits_and_deliveries_reconcile_together():
    r = reconcile([delivery(), visit()], [check_in(t(9, 5)), drop(t(14))], t(14, 5),
                  ambient_c=20.0)
    assert len(r.visits) == 1 and len(r.deliveries) == 1
    assert {f.kind for f in r.findings} == {FindingKind.ON_TIME, FindingKind.PACKAGE_EXPOSED}
