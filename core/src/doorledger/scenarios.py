"""Demo scenarios: a care day for the demo household, replayed at high speed.

Observations here are labelled with their real source. Scenes that come from the Ring
Developer Playground (vehicle arrival, package drop) carry ``Source.RING_LIVE`` and point at
frames captured from those streams; scenes we filmed ourselves (the aide showing her code)
carry ``Source.OWN_FOOTAGE``. Nothing is passed off as Ring footage that isn't.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from .domain import (
    Expectation,
    ExpectationKind,
    MedicationProfile,
    Observation,
    ObservationKind,
    Source,
)
from .engine import Engine

log = logging.getLogger("doorledger.scenarios")

VISIT_ID = "v_morning"


def _at(day: datetime, hh: int, mm: int, tz: ZoneInfo) -> datetime:
    return datetime.combine(day.date(), time(hh, mm), tzinfo=tz)


def day_plan(day: datetime, tz: ZoneInfo) -> list[Expectation]:
    return [
        Expectation(ExpectationKind.CAREGIVER_VISIT, "Morning personal care",
                    _at(day, 9, 0, tz), _at(day, 11, 0, tz), caregiver="Maria",
                    agency="BrightPath Home Care", planned_minutes=120, visit_id=VISIT_ID),
        Expectation(ExpectationKind.MEDICATION_DELIVERY, "Insulin refill (CVS Specialty)",
                    _at(day, 13, 0, tz), _at(day, 17, 0, tz), carrier="UPS",
                    tracking="1Z-DEMO-4471", medication=MedicationProfile()),
    ]


@dataclass
class Step:
    hh: int
    mm: int
    kind: ObservationKind
    source: Source
    visit_id: str | None = None
    evidence: str | None = None
    detail: dict = field(default_factory=dict)


SCENARIOS: dict[str, dict] = {
    "late_short_visit": {
        "start": (8, 50), "end": (10, 20), "ambient_c": 27.0,
        "plan": {ExpectationKind.CAREGIVER_VISIT},
        "steps": [
            Step(9, 22, ObservationKind.PRESENCE_CHECK_IN, Source.OWN_FOOTAGE, VISIT_ID,
                 "evidence/checkin.jpg", {"method": "compact_qr"}),
            Step(10, 5, ObservationKind.PRESENCE_CHECK_OUT, Source.OWN_FOOTAGE, VISIT_ID,
                 "evidence/checkout.jpg", {"method": "compact_qr"}),
        ],
    },
    "porch_heat": {
        "start": (13, 55), "end": (15, 40), "ambient_c": 34.0,
        "plan": {ExpectationKind.MEDICATION_DELIVERY},
        "steps": [
            Step(14, 5, ObservationKind.VEHICLE_ARRIVED, Source.RING_LIVE, None,
                 "evidence/vehicle.jpg", {"note": "delivery van at the curb"}),
            Step(14, 6, ObservationKind.PERSON_AT_DOOR, Source.RING_LIVE, None,
                 "evidence/courier.jpg", {"carrying_package": True}),
            Step(14, 7, ObservationKind.PACKAGE_DROPPED, Source.RING_LIVE, None,
                 "evidence/package.jpg", {"note": "insulated mailer on the doormat"}),
            Step(15, 26, ObservationKind.PACKAGE_REMOVED, Source.RING_LIVE, None,
                 "evidence/package_gone.jpg", {"note": "neighbor picked it up"}),
        ],
    },
}
SCENARIOS["full_day"] = {
    "start": (8, 50), "end": (15, 40), "ambient_c": 34.0,
    "steps": SCENARIOS["late_short_visit"]["steps"] + SCENARIOS["porch_heat"]["steps"],
}


class ScenarioRunner:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.task: asyncio.Task | None = None
        self.name: str | None = None

    def stop(self) -> None:
        if self.task and not self.task.done():
            self.task.cancel()
        self.task = None

    async def start(self, name: str, speed: float = 60.0, day: datetime | None = None) -> None:
        if name not in SCENARIOS:
            raise KeyError(name)
        self.stop()
        spec = SCENARIOS[name]
        tz = ZoneInfo(self.engine.household.patient.timezone)
        day = day or datetime.now(tz)
        self.engine.reset()
        if hasattr(self.engine.ambient, "override_c"):
            self.engine.ambient.override_c = spec["ambient_c"]
        start = _at(day, *spec["start"], tz)
        end = _at(day, *spec["end"], tz)
        clock = self.engine.clock
        if hasattr(clock, "set"):
            clock.set(start, speed)
        kinds = spec.get("plan")
        for e in day_plan(day, tz):
            if kinds is None or e.kind in kinds:
                self.engine.add_expectation(e)
        steps = sorted(spec["steps"], key=lambda s: (s.hh, s.mm))
        self.name = name
        self.task = asyncio.create_task(self._run(steps, day, tz, end))

    async def _run(self, steps: list[Step], day: datetime, tz: ZoneInfo, end: datetime) -> None:
        pending = list(steps)
        try:
            while True:
                now = self.engine.clock.now()
                while pending and _at(day, pending[0].hh, pending[0].mm, tz) <= now:
                    s = pending.pop(0)
                    self.engine.ingest(Observation(
                        kind=s.kind, at=_at(day, s.hh, s.mm, tz), source=s.source,
                        visit_id=s.visit_id, evidence_path=s.evidence, detail=dict(s.detail),
                        device_id=self.engine.device.get("id")))
                self.engine.evaluate(now)
                if now >= end and not pending:
                    if hasattr(self.engine.clock, "pause"):
                        self.engine.clock.pause()
                    return
                await asyncio.sleep(0.25)
        except asyncio.CancelledError:  # pragma: no cover
            pass
        except Exception:  # noqa: BLE001
            log.exception("scenario crashed")
