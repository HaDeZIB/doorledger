"""Live end-to-end run, offline: recorded Ring Developer Playground device + history, the
recorded Playground Package frame as the snapshot, scripted vision, and stubbed Amazon
Connect / Amazon SNS clients. No network, no token, no phone rings."""

import asyncio
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from doorledger import live as live_mod
from doorledger.clock import SimClock
from doorledger.domain import (
    Expectation,
    ExpectationKind,
    MedicationProfile,
    Observation,
    ObservationKind,
    Person,
    Source,
)
from doorledger.engine import Engine
from doorledger.household import demo_household
from doorledger.ledger import Ledger
from doorledger.live import LiveController
from doorledger.live_preflight import PlaygroundReplayRing, probe, token_minutes_left
from doorledger.live_session import (
    CappedNotifier,
    CappedVoice,
    LiveOptions,
    LiveResponder,
    LiveRun,
    LiveTrace,
)
from doorledger.notify import ConnectVoiceNotifier, FanOutNotifier, SNSNotifier
from doorledger.responder import Responder, TemplateWriter
from doorledger.vision import ScriptedVision
from doorledger.watcher import Watcher
from doorledger.weather import AmbientTemperature

VOICE_TO = "+15550111"
SMS_TO = "+15550122"
PACKAGE = {"package_visible": True, "confidence": 0.9, "note": "box on the snowy step"}


@pytest.fixture(autouse=True)
def demo_env(monkeypatch):
    monkeypatch.delenv("RING_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("DOORLEDGER_RING_EVENT_TYPES", raising=False)
    monkeypatch.setenv("DOORLEDGER_VOICE_TO", VOICE_TO)
    monkeypatch.setenv("DOORLEDGER_SMS_TO", SMS_TO)
    # fast snapshot burst: three distinct timestamps 10 ms apart
    monkeypatch.setattr(live_mod, "SNAPSHOT_STEP", timedelta(milliseconds=10))
    monkeypatch.setattr(live_mod, "SNAPSHOT_LAG", timedelta(milliseconds=10))


class FakeConnect:
    """boto3 'connect' client stand-in: records calls, never dials."""

    def __init__(self):
        self.calls: list[dict] = []

    def start_outbound_voice_contact(self, **kw):
        self.calls.append(kw)
        return {"ContactId": f"contact-{len(self.calls)}"}

    def describe_contact(self, **kw):
        return {"Contact": {"ConnectedToSystemTimestamp": datetime.now(UTC)}}


class FakeSNS:
    def __init__(self):
        self.published: list[dict] = []

    def publish(self, **kw):
        self.published.append(kw)
        return {"MessageId": "m"}


def real_channels():
    """The production notifier classes, with their AWS clients replaced by fakes."""
    connect, sns = FakeConnect(), FakeSNS()
    voice = ConnectVoiceNotifier(instance_id="inst", flow_id="flow", source="+15550100",
                                 to=VOICE_TO, client=connect, spawn=lambda fn: fn(),
                                 sleep=lambda s: None, poll_for_s=4, poll_every_s=4)
    sms = SNSNotifier(phone=SMS_TO)
    sms._client = sns
    return voice, sms, connect, sns


def make_engine() -> Engine:
    hh = demo_household()
    return Engine(hh, Ledger(":memory:", household=hh.id),
                  Responder(hh, SNSNotifier(phone=""), TemplateWriter()),
                  SimClock(datetime.now(UTC), speed=1.0),
                  AmbientTemperature(hh.lat, hh.lon, override_c=20.0),
                  device={"id": None, "online": None, "source": "replay"})


def make_run(tmp_path, opts: LiveOptions, *, vision=None, click_after_s=0.05):
    engine = make_engine()
    watcher = Watcher(engine, vision or ScriptedVision([PACKAGE]), tmp_path / "evidence",
                      redact_faces=False)
    live = LiveController(engine, watcher, tmp_path / "replay")
    ring = PlaygroundReplayRing(click_after_s=click_after_s)

    async def factory():
        return ring

    live.ring_factory = factory
    voice, sms, connect, sns = real_channels()
    run = LiveRun(engine, live, watcher, opts, voice=voice, notifier=sms,
                  out_dir=tmp_path / "runs", tick_s=0.05)
    return run, ring, connect, sns


async def until(pred, timeout=5.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not pred():
        if loop.time() > end:
            raise AssertionError("timed out")
        await asyncio.sleep(0.01)


def steps(run) -> list[str]:
    return [s["step"] for s in run.trace.steps]


# ------------------------------------------------------------------ end to end


async def test_playground_click_to_one_call_and_one_sms(tmp_path):
    run, ring, connect, sns = make_run(tmp_path, LiveOptions(poll_s=0.01, minutes=1))
    await run.start()
    try:
        await until(lambda: any(s["step"] == "sms" for s in run.trace.steps))
    finally:
        await run.stop("test")

    # Ring -> frame -> vision -> porch k-of-n -> finding -> call -> sms, in that order
    order = steps(run)
    for a, b in [("armed", "ring_event"), ("ring_event", "frame"), ("frame", "vision"),
                 ("vision", "porch"), ("porch", "finding"), ("finding", "call"), ("call", "sms")]:
        assert order.index(a) < order.index(b), (a, b, order)
    # exactly one call, only to the verified demo phone, with the Spanish SSML; one SMS
    (call,) = connect.calls
    assert call["DestinationPhoneNumber"] == VOICE_TO
    assert call["Attributes"]["ssml"].startswith("<speak>")
    (text,) = sns.published
    assert text["PhoneNumber"] == SMS_TO and "Rosa" in text["Message"]
    # the snapshots were taken at the Ring event's start (distinct timestamps)
    assert len(ring.snapshots) == 3 and len(set(ring.snapshots)) == 3
    assert ring.snapshots[0] == ring.click_at

    obs = run.engine.observations
    assert [o.kind for o in obs] == [ObservationKind.PACKAGE_DROPPED]
    assert obs[0].source == Source.RING_SNAPSHOT

    data = run.to_api()
    assert data["source"] == "live" and data["replay"] is False and data["dry_run"] is False
    lat = data["latency"]
    assert lat["base"] == "ring_event" and lat["ring_event_to_call_ms"] is not None
    assert lat["ring_event_to_call_ms"] >= lat["ring_event_to_decision_ms"] >= 0
    assert data["counts"]["calls_placed"] == 1 and data["counts"]["sms_sent"] == 1
    call_step = next(s for s in data["steps"] if s["step"] == "call")
    assert call_step["detail"]["status"] == "placed" and "connect_ms" in call_step["detail"]
    # the answered outcome arrived (synchronous spawn) and is on the trace
    assert "call_outcome" in steps(run)
    assert not run.trace.active and (tmp_path / "runs" / f"{run.trace.run_id}.json").exists()


async def test_a_second_event_never_calls_again_and_the_ladder_stays_down(tmp_path):
    run, _ring, connect, sns = make_run(tmp_path, LiveOptions(poll_s=0.01, minutes=1))
    await run.start()
    try:
        await until(lambda: len(sns.published) == 1)
        # minutes later the box is still out: no re-call, no Luis, no Ana
        later = datetime.now(UTC) + timedelta(minutes=12)
        run.engine.evaluate(later)
        run.engine.evaluate(later + timedelta(minutes=20))
    finally:
        await run.stop("test")
    assert len(connect.calls) == 1 and len(sns.published) == 1
    assert "skipped" in steps(run)


async def test_dry_run_places_nothing(tmp_path):
    run, _ring, connect, sns = make_run(tmp_path, LiveOptions(poll_s=0.01, dry_run=True))
    await run.start()
    try:
        await until(lambda: "finding" in steps(run) and "sms" in steps(run))
    finally:
        await run.stop("test")
    assert connect.calls == [] and sns.published == []
    assert run.to_api()["dry_run"] is True
    call = next(s for s in run.trace.steps if s["step"] == "call")
    assert "not placed" in call["detail"]["status"]


async def test_whep_trigger_only_records_history_rows(tmp_path, monkeypatch):
    run, ring, connect, _sns = make_run(tmp_path, LiveOptions(poll_s=0.01, trigger="whep"))

    async def no_whep():  # the WHEP loop needs a real Ring session; not under test here
        await asyncio.sleep(3600)

    monkeypatch.setattr(run.live, "_watch_loop", no_whep)
    await run.start()
    try:
        await until(lambda: "ring_event" in steps(run))
        await asyncio.sleep(0.1)
    finally:
        await run.stop("test")
    assert ring.snapshots == [] and connect.calls == []  # timestamped, not acted on
    (ev,) = [s for s in run.trace.steps if s["step"] == "ring_event"]
    assert ev["detail"]["action"] == "recorded"


async def test_no_package_in_the_frame_means_no_call(tmp_path):
    nothing = ScriptedVision([{"package_visible": False, "confidence": 0.9}])
    run, _ring, connect, sns = make_run(tmp_path, LiveOptions(poll_s=0.01), vision=nothing)
    await run.start()
    try:
        await until(lambda: "vision" in steps(run))
        await asyncio.sleep(0.1)
    finally:
        await run.stop("test")
    assert connect.calls == [] and sns.published == [] and run.engine.observations == []


async def test_rehearsal_is_offline_and_labelled(tmp_path):
    run, _ring, connect, sns = make_run(tmp_path, LiveOptions(poll_s=0.01, rehearsal=True))
    await run.start()
    try:
        await until(lambda: "finding" in steps(run))
    finally:
        await run.stop("test")
    data = run.to_api()
    assert data["source"] == "rehearsal" and data["replay"] is True and data["dry_run"] is True
    assert connect.calls == [] and sns.published == []


async def test_api_refuses_demo_runs_during_a_live_run_and_serves_the_trace(tmp_path):
    from doorledger import api
    from fastapi.testclient import TestClient

    client = TestClient(api.app)
    old = api.live_run
    try:
        api.live_run = None
        assert client.get("/api/live/trace").status_code == 404
        run, *_ = make_run(tmp_path, LiveOptions())
        run.arm()
        api.live_run = run
        r = client.get("/api/live/trace")
        assert r.status_code == 200 and r.json()["steps"][0]["step"] == "armed"
        assert client.post("/api/demo/run", json={"scenario": "porch_cold"}).status_code == 409
        assert client.post("/api/demo/reset").status_code == 409
        run.finalize("test")
        assert client.post("/api/demo/reset").status_code == 200
    finally:
        api.live_run = old


# ------------------------------------------------------------------ safety caps


@dataclass
class FakeVoice:
    to: str = VOICE_TO
    calls: int = 0

    def call(self, person, ssml):
        self.calls += 1
        return f"c-{self.calls}"

    def watch(self, contact_id, on_status):
        pass


ROSA = Person("Rosa Martínez", "patient", phone="+15559990000")
LUIS = Person("Luis (neighbor)", "neighbor", phone="+15559990001")


def test_capped_voice_calls_once_and_only_the_patient():
    inner = FakeVoice()
    trace = LiveTrace(LiveOptions(), out_dir=None)
    v = CappedVoice(inner, max_calls=1, trace=trace)
    assert v.call(LUIS, "<speak/>") is None  # only Rosa is ever called
    assert v.call(ROSA, "<speak/>") == "c-1"
    assert v.call(ROSA, "<speak/>") is None  # cap reached
    assert inner.calls == 1 and v.suppressed == 2
    assert [s["step"] for s in trace.steps] == ["suppressed", "call", "suppressed"]


def test_capped_voice_refuses_any_destination_but_the_demo_phone():
    with pytest.raises(ValueError):
        CappedVoice(FakeVoice(to="+15550999"))


def test_capped_sms_sends_once_and_never_to_a_personal_number():
    seen = []

    class Inner:
        channel = "sms"

        def send(self, person, message):
            seen.append(person.phone)
            return True

    n = CappedNotifier(Inner(), max_sms=1)
    assert n.send(ROSA, "hola") is True
    assert n.send(ROSA, "otra vez") is False
    assert seen == [None] and n.suppressed == 1


def test_real_aws_clients_are_refused_under_pytest():
    assert os.environ.get("PYTEST_CURRENT_TEST")
    voice = ConnectVoiceNotifier(instance_id="i", flow_id="f", source="+15550100", to=VOICE_TO)
    with pytest.raises(RuntimeError, match="under pytest"):
        CappedVoice(voice).call(ROSA, "<speak/>")
    with pytest.raises(RuntimeError, match="under pytest"):
        CappedNotifier(FanOutNotifier(SNSNotifier(phone=SMS_TO))).send(ROSA, "hola")


def test_full_ladder_allows_the_recall_but_caps_still_hold():
    hh = demo_household()
    inner = FakeVoice()
    t0 = datetime(2026, 1, 13, 20, 7, tzinfo=UTC)

    class Quiet:
        channel = "sms"

        def send(self, person, message):
            return True

    def drive(full: bool, max_calls: int):
        inner.calls = 0
        r = LiveResponder(hh, CappedNotifier(Quiet(), max_sms=10),
                          TemplateWriter(), voice=CappedVoice(inner, max_calls),
                          full_ladder=full)
        eng = Engine(hh, Ledger(household=hh.id), r, SimClock(t0, speed=0),
                     AmbientTemperature(hh.lat, hh.lon, override_c=-9.0))
        eng.add_expectation(Expectation(ExpectationKind.MEDICATION_DELIVERY, "Insulin",
                                        t0 - timedelta(hours=1), t0 + timedelta(hours=3),
                                        medication=MedicationProfile()))
        eng.ingest(Observation(ObservationKind.PACKAGE_DROPPED, t0, Source.RING_SNAPSHOT))
        for m in (6, 12, 25):
            eng.evaluate(t0 + timedelta(minutes=m))
        return {a["target"] for a in (rec["body"] for rec in eng.ledger.records(kinds=["action"]))}

    assert drive(False, 5) == {"Rosa Martínez"} and inner.calls == 1
    targets = drive(True, 5)
    assert inner.calls == 2 and "Luis (neighbor)" in targets  # re-call at +5, then Luis
    drive(True, 1)
    assert inner.calls == 1  # the cap holds even with the full ladder


# ------------------------------------------------------------------ preflight helpers


def test_token_minutes_left_reads_jwt_exp_only():
    import base64
    import json

    payload = base64.urlsafe_b64encode(json.dumps({"exp": 1_000 + 25 * 60}).encode()).rstrip(b"=")
    token = f"x.{payload.decode()}.y"
    assert round(token_minutes_left(token, now=1_000)) == 25
    assert token_minutes_left("opaque-token") is None


def test_probe_reports_new_rows_and_snapshot_result(tmp_path):
    from ringpartner.models import HistoryEvent, HistoryPage, Media

    start = datetime.now(UTC)
    rows = [[], [HistoryEvent("e-new", "on_demand", start, None, "dev")]]

    class Ring:
        def __init__(self):
            self.calls = 0

        def history(self, device_id):
            page = rows[min(self.calls, 1)] if self.calls else []
            self.calls += 1
            return HistoryPage(page, None)

        def snapshot(self, device_id, at=None):
            return Media(b"jpeg", "image/jpeg", at, "x")

    lines: list[str] = []
    ticks = iter(range(100))
    seen = probe(Ring(), "dev", seconds=3, every=1, out=lines.append, save_dir=tmp_path,
                 sleep=lambda s: None, clock=lambda: next(ticks))
    assert [r["event_type"] for r in seen] == ["on_demand"]
    assert seen[0]["end"] is None and seen[0]["snapshot"].startswith("ok, 4 bytes")
    assert any("on_demand" in line and "open" in line for line in lines)


class FakeBoto:
    """sts / connect / sns stand-ins for the read-only preflight lookups."""

    def __init__(self, service):
        self.service = service

    def get_caller_identity(self):
        return {"Account": "111122223333"}

    def describe_contact_flow(self, **kw):
        return {"ContactFlow": {"Name": "DoorLedger patient alert (es)", "State": "ACTIVE"}}

    def get_sms_sandbox_account_status(self):
        return {"IsInSandbox": True}

    def list_sms_sandbox_phone_numbers(self):
        return {"PhoneNumbers": [{"PhoneNumber": SMS_TO, "Status": "Verified"}]}


def preflight_env(**extra):
    env = {"RING_ACCESS_TOKEN": "opaque-playground-token", "DOORLEDGER_SMS_TO": SMS_TO}
    env.update(extra)
    return env


def replay_ring(token):
    from doorledger.live_preflight import PLAYGROUND_FIXTURES
    from ringpartner import RingClient
    from ringpartner.fixtures import ReplayTransport

    return RingClient(token, transport=ReplayTransport(PLAYGROUND_FIXTURES))


def test_preflight_on_recorded_playground_responses(tmp_path):
    from doorledger.live_preflight import preflight_ok, run_preflight

    full = preflight_env(DOORLEDGER_VOICE_TO=VOICE_TO, DOORLEDGER_CONNECT_INSTANCE_ID="instance-id-77",
                         DOORLEDGER_CONNECT_FLOW_ID="flow-id-88",
                         DOORLEDGER_CONNECT_SOURCE_NUMBER="+15550100")
    checks = run_preflight(full, ring_factory=replay_ring, boto=FakeBoto, bedrock=False,
                           port=1, save_dir=tmp_path)
    by = {c.name: c for c in checks}
    assert by["Ring devices"].ok and "Playground Device" in by["Ring device"].detail
    assert by["Ring history"].ok and "on_demand" in by["Ring history"].detail
    # the recorded snapshot answer is the Playground's 403: a warning, not a blocker
    snap = by["Ring snapshot at the newest event"]
    assert not snap.ok and not snap.critical and "403" in snap.detail
    assert by["Amazon Connect flow"].ok and by["Amazon SNS SMS"].ok
    assert preflight_ok(checks)
    text = "\n".join(c.line() for c in checks)
    for secret in ("opaque-playground-token", VOICE_TO, SMS_TO, "111122223333",
                   "instance-id-77", "flow-id-88"):
        assert secret not in text, secret


def test_preflight_blocks_a_sending_run_without_connect_but_not_a_dry_run():
    from doorledger.live_preflight import preflight_ok, run_preflight

    env = preflight_env()
    assert not preflight_ok(run_preflight(env, ring_factory=replay_ring, boto=FakeBoto,
                                          bedrock=False, port=1))
    assert preflight_ok(run_preflight(env, ring_factory=replay_ring, boto=FakeBoto,
                                      bedrock=False, port=1, dry_run=True))
    no_token = run_preflight({}, ring_factory=replay_ring, boto=FakeBoto, bedrock=False,
                             port=1, dry_run=True)
    assert not preflight_ok(no_token) and "Playground" in no_token[0].detail
