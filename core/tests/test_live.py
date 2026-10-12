"""LiveController: webhook dedupe and dispatch, device status, care windows, replay sessions."""

import asyncio
from datetime import UTC, datetime

import cv2
import numpy as np
import pytest
from doorledger import live as live_mod
from doorledger.clock import SimClock
from doorledger.domain import Expectation, ExpectationKind, MedicationProfile, ObservationKind
from doorledger.engine import Engine
from doorledger.household import demo_household
from doorledger.ledger import Ledger
from doorledger.live import LiveController
from doorledger.notify import ConsoleNotifier
from doorledger.responder import Responder, TemplateWriter
from doorledger.vision import ScriptedVision
from doorledger.watcher import Watcher
from doorledger.weather import AmbientTemperature
from ringpartner.webhooks import WebhookEvent

DAY = datetime(2026, 10, 11, tzinfo=UTC)


def t(hh: int, mm: int = 0) -> datetime:
    return DAY.replace(hour=hh, minute=mm)


def make_engine(now: datetime | None = None) -> Engine:
    hh = demo_household()
    return Engine(hh, Ledger(":memory:", household=hh.id),
                  Responder(hh, ConsoleNotifier(), TemplateWriter()),
                  SimClock(now or t(14), speed=0),
                  AmbientTemperature(hh.lat, hh.lon, override_c=20.0),
                  device={"id": "dev-front", "online": None, "source": "replay"})


def event(type_: str, *, request_id: str | None = "req-1", sub_type: str | None = None,
          id_: str = "evt-1") -> WebhookEvent:
    return WebhookEvent(id=id_, type=type_, device_id="dev-front", timestamp=None,
                        sub_type=sub_type, request_id=request_id)


@pytest.fixture(autouse=True)
def no_ring_token(monkeypatch):
    monkeypatch.delenv("RING_ACCESS_TOKEN", raising=False)


@pytest.fixture
def ctl(tmp_path, monkeypatch):
    c = LiveController(make_engine(), None, tmp_path)
    c.calls = []

    async def fake_watch_once(reason, scene="default", *, burst=False):
        c.calls.append((reason, scene, burst))
        return 0

    monkeypatch.setattr(c, "watch_once", fake_watch_once)
    return c


async def settle():
    for _ in range(3):
        await asyncio.sleep(0)


# ------------------------------------------------------------------ webhooks


async def test_webhook_dedupe_by_request_id(ctl):
    assert await ctl.on_webhook(event("motion_detected", sub_type="human")) == "watching"
    # Ring retries with the same request_id (even if the payload id differs)
    assert await ctl.on_webhook(event("motion_detected", sub_type="human", id_="evt-2")) == "duplicate"
    await settle()
    assert len(ctl.calls) == 1


async def test_webhook_dedupe_falls_back_to_event_id(ctl):
    assert await ctl.on_webhook(event("device_online", request_id=None, id_="e9")) == "recorded"
    assert await ctl.on_webhook(event("device_online", request_id=None, id_="e9")) == "duplicate"
    assert await ctl.on_webhook(event("device_online", request_id=None, id_="e10")) == "recorded"


async def test_button_press_schedules_burst_watch_on_package_scene(ctl):
    assert await ctl.on_webhook(event("button_press", sub_type="vehicle")) == "watching"
    await settle()
    assert ctl.calls == [("webhook:button_press:vehicle", "package", True)]


@pytest.mark.parametrize("sub_type,scene", [
    ("package_delivery", "package"),
    ("vehicle", "vehicle"),
    ("human", "package"),
    ("motion", "default"),
    (None, "default"),
    ("something_new", "default"),
])
async def test_motion_schedules_watch_for_scene(ctl, sub_type, scene):
    assert await ctl.on_webhook(event("motion_detected", sub_type=sub_type)) == "watching"
    await settle()
    assert ctl.calls == [(f"webhook:motion_detected:{sub_type}", scene, False)]


async def test_device_online_offline_updates_engine(ctl):
    assert await ctl.on_webhook(event("device_offline", request_id="a")) == "recorded"
    assert ctl.engine.device["online"] is False
    assert await ctl.on_webhook(event("device_online", request_id="b")) == "recorded"
    assert ctl.engine.device["online"] is True
    await settle()
    assert ctl.calls == []


async def test_other_events_are_recorded_without_watching(ctl):
    assert await ctl.on_webhook(event("app_integration_added")) == "recorded"
    await settle()
    assert ctl.calls == [] and ctl.engine.device["online"] is None


# ------------------------------------------------------------------ care windows


def delivery(start: int, end: int) -> Expectation:
    return Expectation(ExpectationKind.MEDICATION_DELIVERY, "Insulin", t(start), t(end),
                       medication=MedicationProfile())


@pytest.mark.parametrize("now,open_", [
    (t(12, 29), False),
    (t(12, 30), True),   # window_start - 30 min
    (t(15), True),
    (t(17, 30), True),   # window_end + 30 min
    (t(17, 31), False),
])
def test_windows_open_with_padding(tmp_path, now, open_):
    engine = make_engine(now)
    engine.add_expectation(delivery(13, 17))
    assert LiveController(engine, None, tmp_path).windows_open() is open_


def test_windows_closed_without_expectations(tmp_path):
    assert LiveController(make_engine(), None, tmp_path).windows_open() is False


async def test_watch_loop_runs_while_window_open(ctl, monkeypatch):
    monkeypatch.setattr(live_mod, "SESSION_GAP_SECONDS", 0)
    ctl.engine.add_expectation(delivery(13, 17))
    calls = []

    async def watch(reason, scene="default", *, burst=False):
        calls.append(reason)
        if len(calls) == 1:
            raise RuntimeError("WHEP 500")  # transient errors must not stop the loop
        if len(calls) == 3:
            ctl.engine.expectations.clear()  # window closes
        return 0

    monkeypatch.setattr(ctl, "watch_once", watch)
    assert ctl.start_watching() is True
    assert ctl.start_watching() is False  # already running
    await asyncio.wait_for(ctl.watch_task, 2)
    assert calls == ["care_window"] * 3
    ctl.stop_watching()
    assert ctl.watch_task is None


# ------------------------------------------------------------------ watch sessions


async def test_watch_once_without_watcher_is_noop(tmp_path):
    c = LiveController(make_engine(), None, tmp_path)
    assert await c.watch_once("test") == 0
    assert c.sessions == 0


async def test_watch_once_replays_recorded_scene(tmp_path):
    frames = tmp_path / "replay" / "package" / "frames"
    frames.mkdir(parents=True)
    for i in range(8):
        cv2.imwrite(str(frames / f"{i:03d}.jpg"), np.full((360, 640, 3), 120, np.uint8))
    engine = make_engine()
    vision = ScriptedVision([{"package_visible": True, "confidence": 0.9}])
    watcher = Watcher(engine, vision, tmp_path / "evidence", redact_faces=False)
    c = LiveController(engine, watcher, tmp_path / "replay")
    assert await c.watch_once("webhook:button_press", "package") == 1
    assert c.sessions == 1
    assert watcher.frames_seen == 6  # replay sessions are capped at 6 frames
    assert [o.kind for o in engine.observations] == [ObservationKind.PACKAGE_DROPPED]


async def test_watch_once_missing_scene_produces_nothing(tmp_path):
    engine = make_engine()
    watcher = Watcher(engine, ScriptedVision([{}]), tmp_path / "evidence", redact_faces=False)
    c = LiveController(engine, watcher, tmp_path / "replay")
    assert await c.watch_once("care_window", "vehicle") == 0
    assert c.sessions == 1


# ------------------------------------------------------------------ Ring history poller


class FakeHistoryRing:
    """AsyncRingClient stand-in for one poll (no network). Closes the care window after it."""

    def __init__(self, ctl, events):
        self.ctl, self.events = ctl, events
        self.history_calls: list = []
        self.snapshots: list = []

    async def devices(self):
        from types import SimpleNamespace

        return [SimpleNamespace(id="dev-front", name="Front Door", online=True,
                                configurations=None, is_encrypted=False)]

    async def history(self, device_id, event_types=None, page_key=None):
        from ringpartner.models import HistoryPage

        self.history_calls.append(event_types)
        self.ctl.engine.expectations.clear()  # window closes after this poll
        return HistoryPage(self.events(), None)

    async def snapshot(self, device_id, *, at=None):
        from types import SimpleNamespace

        self.snapshots.append(at)
        return SimpleNamespace(content=b"")

    async def aclose(self):
        pass


async def test_history_poller_filters_types_and_ledgers_ring_events(ctl, monkeypatch):
    from datetime import timedelta

    from ringpartner.models import HistoryEvent

    monkeypatch.delenv("DOORLEDGER_RING_EVENT_TYPES", raising=False)
    ctl.engine.add_expectation(delivery(13, 17))

    def events():
        now = datetime.now(UTC)
        # one of OUR live views is running now; Ring logs it as an on_demand row
        ctl.own_sessions.append((now + timedelta(seconds=30), now + timedelta(seconds=55)))
        return [
            HistoryEvent("e-ding", "ding", now + timedelta(seconds=1), None, "dev-front"),
            HistoryEvent("e-play", "on_demand", now + timedelta(seconds=2), None, "dev-front"),
            HistoryEvent("e-ours", "on_demand", now + timedelta(seconds=31), None, "dev-front"),
        ]

    ring = FakeHistoryRing(ctl, events)

    async def fake_ring():
        return ring

    monkeypatch.setattr(ctl, "_ring", fake_ring)
    await asyncio.wait_for(ctl._poll_history_loop(interval=0), 2)

    assert ring.history_calls == [["ding", "on_demand", "motion.human", "motion.vehicle"]]
    # the doorbell press opens a burst session; our own live view never triggers another one
    assert ctl.calls == [("ring_history:ding", "default", True),
                         ("ring_history:on_demand", "default", False)]
    assert len(ring.snapshots) == 2
    recs = ctl.engine.ledger.records(kinds=["ring_event"])
    assert [(r["subtype"], r["body"]["source"], r["body"]["action"]) for r in recs] == [
        ("ding", "ring_history", "burst watch"), ("on_demand", "ring_history", "watch")]
    assert "e-ours" in ctl.seen_events  # seen, so it is not reconsidered on the next poll


def test_history_event_types_env_override(monkeypatch):
    monkeypatch.setenv("DOORLEDGER_RING_EVENT_TYPES", "ding, on_demand,motion")
    assert live_mod.history_event_types() == ["ding", "on_demand", "motion"]
    monkeypatch.setenv("DOORLEDGER_RING_EVENT_TYPES", "")
    assert live_mod.history_event_types() == list(live_mod.HISTORY_EVENT_TYPES)


def test_ring_events_do_not_disturb_state_or_findings(tmp_path):
    """ring_event records sit on the ledger next to the care records; reconciliation and the
    dashboard state ignore them."""
    from ringpartner.models import HistoryEvent

    c = LiveController(make_engine(), None, tmp_path)
    before = c.engine.state()
    c.record_ring_event(HistoryEvent("e1", "motion", t(14, 5), None, "dev-front"), action="watch")
    assert c.engine.state() == before
    (rec,) = c.engine.ledger.records(kinds=["ring_event"])
    assert rec["at"] == t(14, 5).isoformat() and rec["body"]["event_type"] == "motion"
