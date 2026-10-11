"""The engine wires expectations, observations, reconciliation, responder and ledger together."""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any

from .clock import SimClock, WallClock
from .domain import Expectation, Finding, FindingKind, Observation
from .household import Household
from .ledger import Ledger
from .reconcile import Reconciliation, reconcile
from .responder import Responder

log = logging.getLogger("doorledger.engine")

PORCH_OPEN = {FindingKind.PACKAGE_AT_RISK}  # climb the ladder only once time is short


class Engine:
    def __init__(
        self,
        household: Household,
        ledger: Ledger,
        responder: Responder,
        clock: SimClock | WallClock,
        ambient: Any,
        *,
        device: dict[str, Any] | None = None,
    ) -> None:
        self.household = household
        self.ledger = ledger
        self.responder = responder
        self.clock = clock
        self.ambient = ambient
        self.device = device or {"id": household.device_id, "name": household.device_name,
                                 "online": None, "source": "replay"}
        self.expectations: dict[str, Expectation] = {}
        self.observations: list[Observation] = []
        self.visit_secrets: dict[str, bytes] = {}  # visit_id -> presence-code secret
        self._seen: set[tuple[str | None, str, str]] = set()
        self._lock = threading.RLock()
        self.last: Reconciliation | None = None

    # -- inputs ---------------------------------------------------------------------

    def add_expectation(self, e: Expectation) -> None:
        with self._lock:
            self.expectations[e.id] = e
            self.ledger.add_expectation(e)

    def ingest(self, o: Observation) -> None:
        with self._lock:
            self.observations.append(o)
            ref = self._ref_for(o)
            self.ledger.add_observation(o, ref)
        self.evaluate()

    def _ref_for(self, o: Observation) -> str | None:
        if o.visit_id:
            for e in self.expectations.values():
                if e.visit_id == o.visit_id:
                    return e.id
        return None

    # -- core loop ------------------------------------------------------------------

    def evaluate(self, now: datetime | None = None) -> Reconciliation:
        with self._lock:
            now = now or self.clock.now()
            r = reconcile(list(self.expectations.values()), self.observations, now,
                          self.ambient, in_sun=self.household.porch_in_sun)
            self.last = r
            new: list[Finding] = []
            for f in r.findings:
                # Severity is part of the key so "late, not here yet" (warning) and
                # "arrived 22 min late" (info) are both recorded on the timeline.
                key = (f.expectation_id, str(f.kind), str(f.severity))
                if key in self._seen:
                    continue
                self._seen.add(key)
                new.append(f)
                self.ledger.add_finding(f)
            for f in new:
                for a in self.responder.handle(f, now):
                    self.ledger.add_action(a, f.expectation_id)
            open_porch = {f.expectation_id: f for f in r.findings
                          if f.kind in PORCH_OPEN and f.expectation_id}
            for a in self.responder.followup(open_porch, now):
                self.ledger.add_action(a, None)
            return r

    def reset(self) -> None:
        with self._lock:
            self.expectations.clear()
            self.observations.clear()
            self._seen.clear()
            self.responder.incidents.clear()
            self.ledger._db.execute("DELETE FROM records WHERE household = ?", (self.ledger.household,))
            self.ledger._db.commit()

    # -- views ----------------------------------------------------------------------

    def state(self, now: datetime | None = None) -> dict[str, Any]:
        with self._lock:
            now = now or self.clock.now()
            r = reconcile(list(self.expectations.values()), self.observations, now,
                          self.ambient, in_sun=self.household.porch_in_sun)
            records = self.ledger.records(kinds=["finding", "action"])
            return {
                "now": now.isoformat(),
                "visits": [
                    {"expectation": v.expectation.to_dict(),
                     "check_in": v.check_in.to_dict() if v.check_in else None,
                     "check_out": v.check_out.to_dict() if v.check_out else None,
                     "minutes_on_site": None if v.minutes_on_site is None else round(v.minutes_on_site)}
                    for v in r.visits
                ],
                "deliveries": [
                    {"expectation": d.expectation.to_dict(),
                     "dropped": d.dropped.to_dict() if d.dropped else None,
                     "removed": d.removed.to_dict() if d.removed else None,
                     "estimate": d.estimate.as_dict() if d.estimate else None}
                    for d in r.deliveries
                ],
                "findings": [rec["body"] for rec in records if rec["kind"] == "finding"],
                "actions": [rec["body"] for rec in records if rec["kind"] == "action"],
            }
