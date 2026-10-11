"""Deterministic reconciliation: EXPECTED care vs. OBSERVED events -> Findings.

This layer is pure and fully testable. The LLM agent sits on top of it and decides *what to
do* about findings (who to message, how to phrase it, whether to request a backup aide); it
never decides *whether* a visit happened. Ground truth stays deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable

from . import exposure
from .domain import (
    Expectation,
    ExpectationKind,
    Finding,
    FindingKind,
    Observation,
    ObservationKind,
    Severity,
)

AmbientFn = Callable[[datetime], float]

LATE_GRACE = timedelta(minutes=15)
MISSED_AFTER = timedelta(minutes=45)
SHORT_VISIT_RATIO = 0.75
DROP_MATCH_BEFORE = timedelta(minutes=60)
DROP_MATCH_AFTER = timedelta(minutes=180)
OVERDUE_AFTER = timedelta(minutes=60)


@dataclass
class VisitState:
    expectation: Expectation
    check_in: Observation | None = None
    check_out: Observation | None = None

    @property
    def minutes_on_site(self) -> float | None:
        if self.check_in and self.check_out:
            return (self.check_out.at - self.check_in.at).total_seconds() / 60
        return None


@dataclass
class DeliveryState:
    expectation: Expectation
    dropped: Observation | None = None
    removed: Observation | None = None
    estimate: exposure.ExposureEstimate | None = None


@dataclass
class Reconciliation:
    findings: list[Finding] = field(default_factory=list)
    visits: list[VisitState] = field(default_factory=list)
    deliveries: list[DeliveryState] = field(default_factory=list)


def _fmt(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def reconcile(
    expectations: list[Expectation],
    observations: list[Observation],
    now: datetime,
    ambient_c: AmbientFn | float = 25.0,
    *,
    in_sun: bool = False,
) -> Reconciliation:
    ambient = ambient_c if callable(ambient_c) else (lambda _t, v=ambient_c: v)
    obs = sorted((o for o in observations if o.at <= now), key=lambda o: o.at)
    result = Reconciliation()
    used: set[str] = set()

    for exp in sorted(expectations, key=lambda e: e.window_start):
        if exp.kind == ExpectationKind.CAREGIVER_VISIT:
            result.visits.append(_visit(exp, obs, now, result.findings))
    for exp in sorted(expectations, key=lambda e: e.window_start):
        if exp.kind == ExpectationKind.MEDICATION_DELIVERY:
            result.deliveries.append(_delivery(exp, obs, now, ambient, in_sun, used, result.findings))
    return result


def _visit(exp: Expectation, obs: list[Observation], now: datetime, out: list[Finding]) -> VisitState:
    st = VisitState(exp)
    lo = exp.window_start - timedelta(minutes=30)
    for o in obs:
        if o.visit_id != exp.visit_id:
            continue
        if o.kind == ObservationKind.PRESENCE_CHECK_IN and st.check_in is None and o.at >= lo:
            st.check_in = o
        elif o.kind == ObservationKind.PRESENCE_CHECK_OUT and st.check_in and o.at > st.check_in.at:
            st.check_out = o

    who = exp.caregiver or "The caregiver"
    if st.check_in is None:
        if now > exp.window_start + MISSED_AFTER:
            out.append(Finding(FindingKind.MISSED_VISIT, Severity.CRITICAL, now,
                               f"{who} has not arrived for the {_fmt(exp.window_start)} visit "
                               f"({int((now - exp.window_start).total_seconds() // 60)} min).",
                               exp.id))
        elif now > exp.window_start + LATE_GRACE:
            out.append(Finding(FindingKind.LATE_ARRIVAL, Severity.WARNING, now,
                               f"{who} is late for the {_fmt(exp.window_start)} visit.", exp.id))
        return st

    late_by = (st.check_in.at - exp.window_start).total_seconds() / 60
    if late_by > LATE_GRACE.total_seconds() / 60:
        out.append(Finding(FindingKind.LATE_ARRIVAL, Severity.INFO, st.check_in.at,
                           f"{who} checked in {int(late_by)} min late at {_fmt(st.check_in.at)}.",
                           exp.id, [st.check_in.id], {"late_minutes": round(late_by)}))
    else:
        out.append(Finding(FindingKind.ON_TIME, Severity.INFO, st.check_in.at,
                           f"{who} checked in at {_fmt(st.check_in.at)}.", exp.id, [st.check_in.id]))

    if st.check_out is not None:
        mins = st.minutes_on_site or 0
        planned = exp.planned_minutes or 0
        ids = [st.check_in.id, st.check_out.id]
        data = {"minutes_on_site": round(mins), "planned_minutes": planned}
        if planned and mins < planned * SHORT_VISIT_RATIO:
            out.append(Finding(FindingKind.SHORT_VISIT, Severity.WARNING, st.check_out.at,
                               f"{who} stayed {int(mins)} of {planned} planned minutes.",
                               exp.id, ids, data))
        else:
            out.append(Finding(FindingKind.VISIT_COMPLETED, Severity.INFO, st.check_out.at,
                               f"Visit completed: {int(mins)} min on site.", exp.id, ids, data))
    return st


def _delivery(
    exp: Expectation,
    obs: list[Observation],
    now: datetime,
    ambient: AmbientFn,
    in_sun: bool,
    used: set[str],
    out: list[Finding],
) -> DeliveryState:
    st = DeliveryState(exp)
    for o in obs:
        if o.id in used:
            continue
        if (o.kind == ObservationKind.PACKAGE_DROPPED and st.dropped is None
                and exp.window_start - DROP_MATCH_BEFORE <= o.at <= exp.window_end + DROP_MATCH_AFTER):
            st.dropped = o
            used.add(o.id)
        elif o.kind == ObservationKind.PACKAGE_REMOVED and st.dropped and o.at > st.dropped.at:
            st.removed = o
            used.add(o.id)
            break

    label = exp.medication.name if exp.medication else exp.title
    if st.dropped is None:
        if now > exp.window_end + OVERDUE_AFTER:
            out.append(Finding(FindingKind.DELIVERY_OVERDUE, Severity.WARNING, now,
                               f"{label} delivery expected by {_fmt(exp.window_end)} has not arrived.",
                               exp.id))
        return st

    end = st.removed.at if st.removed else now
    amb = ambient(end)
    st.estimate = exposure.estimate(st.dropped.at, end, amb, exp.medication, in_sun=in_sun)
    est = st.estimate.as_dict()
    ids = [st.dropped.id] + ([st.removed.id] if st.removed else [])

    if st.removed:
        sev = Severity.CRITICAL if st.estimate.status == "compromised" else Severity.INFO
        out.append(Finding(FindingKind.PACKAGE_RETRIEVED, sev, st.removed.at,
                           f"{label} brought inside after {int(st.estimate.minutes_on_porch)} min "
                           f"(est. {st.estimate.estimated_internal_c} °C inside the box).",
                           exp.id, ids, est))
        return st

    if st.estimate.status == "compromised":
        out.append(Finding(FindingKind.PACKAGE_COMPROMISED, Severity.CRITICAL, now,
                           f"{label} has been on the porch {int(st.estimate.minutes_on_porch)} min at "
                           f"{amb:.0f} °C; it may no longer be safe to use.", exp.id, ids, est))
    elif st.estimate.status == "at_risk":
        out.append(Finding(FindingKind.PACKAGE_AT_RISK, Severity.WARNING, now,
                           f"{label} on the porch {int(st.estimate.minutes_on_porch)} min at {amb:.0f} °C; "
                           f"bring it inside soon.", exp.id, ids, est))
    else:
        out.append(Finding(FindingKind.PACKAGE_EXPOSED, Severity.INFO, st.dropped.at,
                           f"{label} delivered at {_fmt(st.dropped.at)}.", exp.id, ids, est))
    return st
