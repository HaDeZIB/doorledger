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

VISIT_ID = "V-MORNING"  # QR alphanumeric set: [A-Z0-9-]


def demo_visit_secret() -> bytes:
    """Secret for the demo visit. Fixed (from env or fixtures) so footage we film with the
    Caregiver Pass can be verified again when it is replayed; random otherwise."""
    import json
    import os
    from pathlib import Path

    from . import presence

    if os.environ.get("DOORLEDGER_VISIT_SECRET"):
        return presence.secret_from_b64url(os.environ["DOORLEDGER_VISIT_SECRET"])
    meta = Path(__file__).resolve().parents[3] / "fixtures" / "own_footage" / "visit.json"
    if meta.exists():
        return presence.secret_from_b64url(json.loads(meta.read_text())["secret_b64url"])
    return presence.new_visit_secret()


def _at(day: datetime, hh: int, mm: int, tz: ZoneInfo) -> datetime:
    return datetime.combine(day.date(), time(hh, mm), tzinfo=tz)


def day_plan(day: datetime, tz: ZoneInfo) -> list[Expectation]:
    return [
        Expectation(ExpectationKind.CAREGIVER_VISIT, "Morning personal care",
                    _at(day, 9, 0, tz), _at(day, 11, 0, tz), caregiver="Maria",
                    agency="BrightPath Home Care", planned_minutes=120, visit_id=VISIT_ID),
        Expectation(ExpectationKind.MEDICATION_DELIVERY, "Insulin refill (pharmacy)",
                    _at(day, 13, 0, tz), _at(day, 17, 0, tz), carrier="Courier",
                    tracking="DEMO-4471", medication=MedicationProfile()),
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
    frames: str | None = None  # run real Ring footage from fixtures/raw/<frames>/frames instead
    limit: int = 8


SCENARIOS: dict[str, dict] = {
    "late_short_visit": {
        "start": (8, 50), "end": (10, 20), "ambient_c": -6.0,
        "plan": {ExpectationKind.CAREGIVER_VISIT},
        "steps": [
            # Until our own footage is recorded these two are simulated (and labelled so).
            Step(9, 22, ObservationKind.PRESENCE_CHECK_IN, Source.SIMULATED, VISIT_ID,
                 None, {"method": "compact_qr"}, frames="own:checkin"),
            Step(10, 5, ObservationKind.PRESENCE_CHECK_OUT, Source.SIMULATED, VISIT_ID,
                 None, {"method": "compact_qr"}, frames="own:checkout"),
        ],
    },
    # Winter: the Ring Playground "Package" clip is a snowy doorstep, so the porch story is
    # insulin left out in the freezing cold (frozen insulin must be discarded).
    "porch_cold": {
        "start": (13, 55), "end": (14, 55), "ambient_c": -9.0,
        "plan": {ExpectationKind.MEDICATION_DELIVERY},
        "steps": [
            # (The Playground Vehicle clip is a green spring parking lot, so it is not used in
            #  this winter story.) Fallback source is SIMULATED; the real one comes from footage.
            Step(14, 7, ObservationKind.PACKAGE_DROPPED, Source.SIMULATED, None,
                 None, {"note": "parcel on the doorstep"}, frames="package"),
            Step(14, 40, ObservationKind.PACKAGE_REMOVED, Source.SIMULATED, None,
                 None, {"note": "neighbor picked it up"}, frames="own:pickup"),
        ],
    },
}
SCENARIOS["porch_heat"] = SCENARIOS["porch_cold"]  # legacy name used by older dashboard builds
SCENARIOS["full_day"] = {
    "start": (8, 50), "end": (14, 55), "ambient_c": -9.0,
    "steps": SCENARIOS["late_short_visit"]["steps"] + SCENARIOS["porch_cold"]["steps"],
}


class ScenarioRunner:
    def __init__(self, engine: Engine, watcher=None, frames_root=None) -> None:
        self.engine = engine
        self.watcher = watcher  # when set, steps with `frames` go through real perception
        self.frames_root = frames_root
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
        self.engine.visit_secrets[VISIT_ID] = demo_visit_secret()
        kinds = spec.get("plan")
        for e in day_plan(day, tz):
            if kinds is None or e.kind in kinds:
                self.engine.add_expectation(e)
        steps = sorted(spec["steps"], key=lambda s: (s.hh, s.mm))
        self.name = name
        self.task = asyncio.create_task(self._run(steps, day, tz, end))

    def _source_for(self, s: Step, day: datetime, tz: ZoneInfo):
        """Recorded footage for a step: Ring Playground frames, or our own clip ("own:<clip>")."""
        import json
        from pathlib import Path

        from .watcher import ReplaySource

        start = _at(day, s.hh, s.mm, tz)
        if s.frames.startswith("own:"):
            clip_dir = Path(__file__).resolve().parents[3] / "fixtures" / "own_footage" / s.frames[4:]
            meta_path = clip_dir / "clip.json"
            if not meta_path.exists():
                return None
            meta = json.loads(meta_path.read_text())
            return ReplaySource(clip_dir / "frames", start, fps=2.0, capture_fps=meta["fps"],
                                source=Source.OWN_FOOTAGE, recorded_start=meta["recorded_start"])
        if self.frames_root is None or not (self.frames_root / s.frames).exists():
            return None
        return ReplaySource(self.frames_root / s.frames / "frames", start, limit=s.limit,
                            capture_fps=1.0)

    async def _run(self, steps: list[Step], day: datetime, tz: ZoneInfo, end: datetime) -> None:
        pending = list(steps)
        try:
            while True:
                now = self.engine.clock.now()
                while pending and _at(day, pending[0].hh, pending[0].mm, tz) <= now:
                    s = pending.pop(0)
                    src = self._source_for(s, day, tz) if s.frames and self.watcher else None
                    if src is not None:
                        if s.kind == ObservationKind.PACKAGE_REMOVED:
                            # the clip starts with the parcel already on the porch
                            self.watcher.tracker(src.source).seed(package_present=True)
                        # Freeze simulated time while the vision model works so the demo
                        # timeline matches the footage, then resume where the frames ended.
                        clock = self.engine.clock
                        if hasattr(clock, "pause"):
                            clock.pause()
                        try:
                            found = await self.watcher.process(src.frames())
                        finally:
                            if hasattr(clock, "set"):
                                clock.set(max(clock.now(), _at(day, s.hh, s.mm, tz)
                                              + timedelta(seconds=len(src.files) / src.fps)))
                        if any(o.kind == s.kind for o in found):
                            continue
                        log.warning("footage %s did not yield %s; using scripted step", s.frames, s.kind)
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
