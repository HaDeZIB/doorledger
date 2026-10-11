"""Read-only snapshot used by the AgentCore CareAgent (no network)."""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from doorledger.agent import CareTools, replay_scenario
from doorledger.aws.snapshot import (
    ReadOnlyNotifier,
    engine_from_snapshot,
    export_snapshot,
)
from doorledger.clock import SimClock
from doorledger.domain import utcnow
from doorledger.engine import Engine
from doorledger.household import demo_household
from doorledger.ledger import Ledger
from doorledger.responder import Responder, TemplateWriter
from doorledger.weather import AmbientTemperature

TZ = ZoneInfo("America/Chicago")
DAY = datetime(2026, 10, 11, tzinfo=TZ)


class Recorder:
    channel = "test"

    def __init__(self):
        self.sent = []

    def send(self, person, message):
        self.sent.append((person.name, message))
        return True


@pytest.fixture(scope="module")
def live_engine():
    hh = demo_household()
    hh.people[0].phone = "+15550000000"  # must never leave the API
    eng = Engine(hh, Ledger(household=hh.id), Responder(hh, Recorder(), TemplateWriter()),
                 SimClock(utcnow(), 0.0), AmbientTemperature(hh.lat, hh.lon, override_c=-9.0))
    replay_scenario(eng, "full_day", DAY)
    return eng


def test_snapshot_is_json_and_strips_contact_details(live_engine):
    snap = export_snapshot(live_engine)
    text = json.dumps(snap)
    assert "+15550000000" not in text
    assert all("phone" not in p and "telegram_chat_id" not in p
               for p in snap["household"]["people"])
    assert snap["version"] == 1 and snap["ambient_c"] == -9.0
    assert len(snap["records"]) == len(live_engine.ledger.records())


def test_rebuilt_engine_gives_identical_tool_output(live_engine):
    snap = json.loads(json.dumps(export_snapshot(live_engine)))  # through the wire
    sealed = engine_from_snapshot(snap)
    a, b = CareTools(live_engine), CareTools(sealed)
    assert json.loads(a.get_today_status()) == json.loads(b.get_today_status())
    assert a.get_timeline(0) == b.get_timeline(0)
    assert a.export_evv() == b.export_evv()


def test_rebuilt_engine_cannot_send(live_engine):
    sealed = engine_from_snapshot(export_snapshot(live_engine))
    assert isinstance(sealed.responder.notifier, ReadOnlyNotifier)
    with pytest.raises(PermissionError):
        sealed.responder.notifier.send(sealed.household.people[0], "hi")
    # Rebuilding does not re-run the rules (no new findings/actions appear).
    assert len(sealed.ledger.records()) == len(live_engine.ledger.records())


def test_rebuilt_clock_is_frozen(live_engine):
    snap = export_snapshot(live_engine)
    sealed = engine_from_snapshot(snap)
    assert sealed.clock.now().isoformat() == snap["now"]
    assert sealed.clock.now() == sealed.clock.now()


def test_bad_snapshot_is_rejected():
    with pytest.raises(ValueError):
        engine_from_snapshot({"version": 99})
    with pytest.raises(ValueError):
        engine_from_snapshot(None)
