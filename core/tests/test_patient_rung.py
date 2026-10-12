"""Rosa's rung of the porch ladder: call + SMS at minute 0, a second call at +5, the neighbor
earlier when time is short, cancel everything when Ring sees the pickup, and Amazon Connect
voice calls (stubbed: no real AWS call, no phone rings)."""

from datetime import UTC, datetime, timedelta

import boto3
import pytest
from botocore.stub import Stubber
from doorledger.domain import Finding, FindingKind, Person, Severity
from doorledger.household import demo_household
from doorledger.ledger import Ledger
from doorledger.notify import ConnectVoiceNotifier, default_voice, demo_envelope
from doorledger.responder import (
    LADDER_GAP,
    MIN_GAP,
    BedrockWriter,
    Incident,
    Responder,
    TemplateWriter,
    rung_gap,
)
from test_responder import ANA, LUIS, ROSA, Recorder

T0 = datetime(2026, 1, 13, 20, 7, tzinfo=UTC)  # 14:07 in Chicago
EXP = "exp_delivery"
MEDICAL = ("insulin", "medic", "diabet", "refriger", "fridge", "pharmac")


class FakeVoice:
    """Stands in for ConnectVoiceNotifier: records calls, never dials."""

    channel = "voice"
    enabled = True

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls: list[tuple[str, str]] = []
        self.watching: dict[str, object] = {}

    def call(self, person, ssml):
        self.calls.append((person.name, ssml))
        return None if self.fail else f"contact-{len(self.calls)}"

    def watch(self, contact_id, on_status):
        self.watching[contact_id] = on_status


def porch(minutes: float, left: float | None = 40.0, kind=FindingKind.PACKAGE_EXPOSED,
          severity=Severity.INFO, **extra) -> Finding:
    """The porch finding as reconcile re-derives it ``minutes`` after the drop."""
    data = {"ambient_c": -9.0, "direction": "cold", "minutes_on_porch": minutes,
            "estimated_internal_c": 3.0, "status": "safe", **extra}
    if left is not None:
        data["minutes_until_excursion_max"] = max(left - minutes, 0.0)
    return Finding(kind, severity, T0, "Insulin delivered at 14:07.", EXP, data=data, id="fnd_x")


def make(voice=None, writer=None):
    rec = Recorder()
    return Responder(demo_household(), rec, writer or TemplateWriter(), voice=voice), rec


def run(r: Responder, minutes: range, left: float | None = 40.0) -> list:
    out = []
    for m in minutes:
        out += r.followup({EXP: porch(m, left)}, T0 + timedelta(minutes=m))
    return out


def by_minute(actions) -> list[tuple[int, str, str]]:
    return [(int((a.at - T0).total_seconds() // 60), a.target, a.data["channel"]) for a in actions]


# ------------------------------------------------------------------ minute 0: call + SMS


def test_call_and_sms_at_minute_zero_with_the_same_content():
    voice = FakeVoice()
    r, rec = make(voice)
    call, sms = r.handle(porch(0), T0)
    assert (call.target, call.data["channel"], call.data["via"]) == (ROSA, "voice", "voice")
    assert call.data["status"] == "placed" and call.data["contact_id"] == "contact-1"
    assert call.delivered is True and call.at == sms.at == T0
    assert (sms.target, sms.data["channel"]) == (ROSA, "sms")
    # one call, placed with the fixed Spanish SSML; same facts and same action in the SMS
    ((to, ssml),) = voice.calls
    assert to == ROSA and ssml == call.data["ssml"]
    assert ssml.startswith('<speak><prosody rate="88%">Hola, señora Rosa. Le llamamos de parte '
                           "de su hija Ana.")
    for words in ("su insulina está", "mucho frío", "póngala en el refri",
                  "Si hay hielo en el escalón, no salga sola", "Luis", "No tiene que contestar"):
        assert words in call.message and words in sms.message, words
    assert rec.sent == [(ROSA, sms.message)]  # the SMS went through the text notifier
    assert r.incidents[EXP].messages == 1  # call + SMS = one contact


def test_without_connect_the_call_is_scripted_but_not_placed():
    r, rec = make(voice=None)
    call, sms = r.handle(porch(0), T0)
    assert sms.data["channel"] == "sms"
    assert call.data["status"] == "not_placed" and call.data["via"] == "app"
    assert call.delivered is False and call.message.startswith("Hola, señora Rosa.")
    assert len(rec.sent) == 1  # only the SMS left (to the console/SNS notifier)


# ------------------------------------------------------------------ +5: call again


def test_second_call_at_five_minutes_if_still_outside():
    voice = FakeVoice()
    r, _ = make(voice)
    r.handle(porch(0), T0)
    out = run(r, range(1, 10))
    assert by_minute(out) == [(5, ROSA, "voice")]  # no second SMS, nobody else yet
    assert out[0].data["attempt"] == 2 and out[0].data["status"] == "placed"
    assert len(voice.calls) == 2 and voice.calls[0][1] == voice.calls[1][1]  # same script


def test_no_second_call_once_ring_sees_the_pickup():
    voice = FakeVoice()
    r, _ = make(voice)
    r.handle(porch(0), T0)
    r.handle(porch(3, kind=FindingKind.PACKAGE_RETRIEVED), T0 + timedelta(minutes=3))
    assert run(r, range(4, 60)) == []
    assert len(voice.calls) == 1


# ------------------------------------------------------------------ deadline-aware ladder


def test_rung_gap_squeezes_when_time_is_short():
    assert rung_gap(None, 2) == LADDER_GAP
    assert rung_gap(60, 2) == LADDER_GAP
    assert rung_gap(15, 2) == timedelta(minutes=5)
    assert rung_gap(1, 2) == MIN_GAP
    assert rung_gap(-3, 1) == MIN_GAP


def test_ladder_with_time_to_spare():
    r, _ = make(FakeVoice())
    first = r.handle(porch(0, left=40), T0)
    rest = run(r, range(1, 40), left=40)
    assert by_minute(first + rest) == [(0, ROSA, "voice"), (0, ROSA, "sms"), (5, ROSA, "voice"),
                                       (10, LUIS, "sms"), (20, ANA, "sms")]


def test_neighbor_asked_earlier_when_little_time_remains():
    """20 min before the box is estimated to freeze: Luis is asked at +5 (with Rosa's second
    call), not +10, and Ana at +10, while there is still time to act."""
    r, _ = make(FakeVoice())
    first = r.handle(porch(0, left=20), T0)
    rest = run(r, range(1, 20), left=20)
    assert by_minute(first + rest) == [(0, ROSA, "voice"), (0, ROSA, "sms"), (5, ROSA, "voice"),
                                       (5, LUIS, "sms"), (10, ANA, "sms")]


def test_at_risk_after_quiet_exposure_uses_the_same_squeezed_gap():
    r, _ = make()
    r.handle(porch(0, left=24), T0)
    out = r.handle(porch(6, left=24, kind=FindingKind.PACKAGE_AT_RISK,
                         severity=Severity.WARNING), T0 + timedelta(minutes=6))
    assert [a.target for a in out] == [LUIS]  # 18 min left / 3 = 6 min gap


# ------------------------------------------------------------------ the doorbell is the reply


def test_pickup_cancels_every_pending_step_and_logs_it():
    voice = FakeVoice()
    r, rec = make(voice)
    r.handle(porch(0), T0)
    picked = Finding(FindingKind.PACKAGE_RETRIEVED, Severity.INFO, T0 + timedelta(minutes=3),
                     "Insulin brought inside after 3 min.", EXP,
                     data={"direction": "cold", "minutes_on_porch": 3.0,
                           "estimated_internal_c": 4.6, "status": "safe"})
    out = r.handle(picked, T0 + timedelta(minutes=3))
    cancelled = [a for a in out if a.kind == "cancelled"]
    assert [(a.target, a.data["channel"]) for a in cancelled] == [
        (ROSA, "voice"), (LUIS, "sms"), (ANA, "sms")]
    assert [a.message.split(":")[0] for a in cancelled] == [
        "Second call to Rosa not needed", "Text to Luis not needed", "Text to Ana not needed"]
    assert all("Ring saw the box picked up at 2:10 PM. The doorbell is Rosa's reply."
               in a.message for a in cancelled)
    assert all(a.delivered is False and a.data["reason"] == "ring_saw_pickup" for a in cancelled)
    assert r.incidents[EXP].closed
    # nothing else is ever sent about it
    n_calls, n_sent = len(voice.calls), len(rec.sent)
    assert run(r, range(4, 60)) == []
    assert (len(voice.calls), len(rec.sent)) == (n_calls, n_sent)


# ------------------------------------------------------------------ fixed wording, no LLM


class FakeBedrock:
    def __init__(self):
        self.prompts: list[str] = []

    def converse(self, **kw):
        self.prompts.append(kw["messages"][0]["content"][0]["text"])
        return {"output": {"message": {"content": [{"text": "LLM WROTE THIS"}]}}}


def bedrock_writer() -> tuple[BedrockWriter, FakeBedrock]:
    w = BedrockWriter.__new__(BedrockWriter)  # skip boto3 client creation
    w.models, w.fallback, w.client = ["m"], TemplateWriter(), FakeBedrock()
    return w, w.client


def test_rosa_and_luis_never_get_llm_text():
    writer, llm = bedrock_writer()
    r, _ = make(FakeVoice(), writer)
    out = r.handle(porch(0), T0) + run(r, range(1, 25))
    msgs = {(a.target, a.data["channel"]): a for a in out}
    for key in ((ROSA, "voice"), (ROSA, "sms"), (LUIS, "sms")):
        assert msgs[key].data["writer"] == "template"
        assert "LLM WROTE THIS" not in msgs[key].message
    assert msgs[(ANA, "sms")].message == "LLM WROTE THIS"  # family wording may use the LLM
    assert len(llm.prompts) == 1 and "Recipient: Ana" in llm.prompts[0]


def test_agent_text_to_rosa_is_replaced_by_the_fixed_template():
    import json
    from zoneinfo import ZoneInfo

    from doorledger.agent import CareTools
    from doorledger.clock import SimClock
    from doorledger.domain import Observation, ObservationKind, Source
    from doorledger.engine import Engine
    from doorledger.scenarios import day_plan
    from doorledger.weather import AmbientTemperature

    hh = demo_household()
    rec = Recorder()
    eng = Engine(hh, Ledger(household=hh.id), Responder(hh, rec, TemplateWriter()),
                 SimClock(T0, 0.0), AmbientTemperature(hh.lat, hh.lon, override_c=15.0))
    tz = ZoneInfo(hh.patient.timezone)
    (exp,) = [e for e in day_plan(T0.astimezone(tz), tz) if e.medication]
    eng.add_expectation(exp)
    eng.ingest(Observation(ObservationKind.PACKAGE_DROPPED, T0, Source.RING_LIVE))
    assert rec.sent == []  # mild day: the rules leave it to the agent
    eng.responder.incidents[exp.id] = Incident(exp.id, "porch", T0)
    tools = CareTools(eng)
    tools.active_incident = exp.id
    r = json.loads(tools.notify(ROSA, "Rosa, go get your insulin from the porch now!", "test"))
    assert r["sent"] is True and "fixed template" in r["wording"]
    assert rec.sent[-1][1].startswith("Señora Rosa, de parte de su hija Ana:")
    assert all("go get your insulin" not in m for _, m in rec.sent)
    agent_rows = [x["body"] for x in eng.ledger.records(kinds=["action"])
                  if x["body"]["data"].get("origin") == "agent"]
    assert [a["data"]["channel"] for a in agent_rows] == ["voice", "sms"]


def test_neighbor_actions_carry_no_medical_details():
    r, _ = make(FakeVoice())
    out = r.handle(porch(0), T0) + run(r, range(1, 25))
    (luis,) = [a for a in out if a.target == LUIS]
    assert not any(w in luis.message.lower() for w in MEDICAL), luis.message
    assert "must not stay out in the cold" in luis.message


# ------------------------------------------------------------------ voice failures fall back


def test_failed_call_at_minute_zero_still_sends_the_sms_once():
    r, rec = make(FakeVoice(fail=True))
    call, sms = r.handle(porch(0), T0)
    assert call.data["status"] == "failed" and call.delivered is False
    assert call.data["via"] == "voice"
    assert sms.data["channel"] == "sms" and "fallback_for" not in sms.data
    assert len(rec.sent) == 1  # no duplicate SMS


def test_failed_second_call_falls_back_to_sms_and_the_ladder_continues():
    r, rec = make(FakeVoice(fail=True))
    r.handle(porch(0), T0)
    out = run(r, range(1, 25))
    recall, fallback = out[0], out[1]
    assert recall.data["status"] == "failed" and recall.data["attempt"] == 2
    assert fallback.data["channel"] == "sms" and fallback.data["fallback_for"] == "voice"
    assert fallback.data["via"] == "test" and fallback.target == ROSA
    assert by_minute(out)[2:] == [(10, LUIS, "sms"), (20, ANA, "sms")]
    assert [n for n, _ in rec.sent] == [ROSA, ROSA, LUIS, ANA]


def test_connect_errors_never_raise(monkeypatch):
    client = boto3.client("connect", region_name="us-east-1", aws_access_key_id="x",
                          aws_secret_access_key="x")
    v = ConnectVoiceNotifier(instance_id="i", flow_id="f", source="+15550100",
                             to="+15550111", client=client)
    with Stubber(client) as stub:
        stub.add_client_error("start_outbound_voice_contact", "LimitExceededException")
        assert v.call(Person("Rosa", "patient"), "<speak>x</speak>") is None
        stub.add_client_error("describe_contact", "ResourceNotFoundException")
        assert v.status("c-1") is None
    r = Responder(demo_household(), Recorder(), TemplateWriter(), voice=v)
    with Stubber(client) as stub:
        stub.add_client_error("start_outbound_voice_contact", "AccessDeniedException")
        call, sms = r.handle(porch(0), T0)
    assert call.data["status"] == "failed" and sms.data["channel"] == "sms"


# ------------------------------------------------------------------ Amazon Connect (stubbed)


def connect_stub():
    client = boto3.client("connect", region_name="us-east-1", aws_access_key_id="x",
                          aws_secret_access_key="x")
    v = ConnectVoiceNotifier(instance_id="inst-1", flow_id="flow-1", source="+15550100",
                             to="+15550111", client=client, spawn=lambda fn: fn(),
                             sleep=lambda s: None, poll_for_s=12, poll_every_s=4)
    return v, client


def test_connect_call_goes_only_to_the_demo_phone_with_ssml_attribute():
    v, client = connect_stub()
    rosa = Person("Rosa Martínez", "patient", phone="+15559999999")  # never dialled
    with Stubber(client) as stub:
        stub.add_response("start_outbound_voice_contact", {"ContactId": "c-42"}, {
            "InstanceId": "inst-1", "ContactFlowId": "flow-1",
            "DestinationPhoneNumber": "+15550111", "SourcePhoneNumber": "+15550100",
            "Attributes": {"ssml": "<speak>hola</speak>"}})
        assert v.call(rosa, "<speak>hola</speak>") == "c-42"
        stub.assert_no_pending_responses()


@pytest.mark.parametrize("contact,expected", [
    ({"ConnectedToSystemTimestamp": datetime(2026, 1, 13, 20, 7, 20)}, "answered"),
    ({"DisconnectTimestamp": datetime(2026, 1, 13, 20, 8)}, "no_answer"),
])
def test_call_outcome_updates_the_ledger(contact, expected):
    v, client = connect_stub()
    hh = demo_household()
    ledger = Ledger(household=hh.id)
    r = Responder(hh, Recorder(), TemplateWriter(), voice=v, on_update=ledger.update_action)
    with Stubber(client) as stub:
        stub.add_response("start_outbound_voice_contact", {"ContactId": "c-7"})
        # first poll: still ringing; second: the outcome
        stub.add_response("describe_contact", {"Contact": {"Id": "c-7"}})
        stub.add_response("describe_contact", {"Contact": {"Id": "c-7", **contact}})
        call, _sms = r.handle(porch(0), T0)
        stub.assert_no_pending_responses()
    # (synchronous spawn: the outcome arrived before the action was first stored)
    assert call.data["status"] == expected
    ledger.add_action(call, EXP)
    call.data["status"] = "placed"
    r._call_outcome(call, expected)  # a later outcome rewrites the stored record in place
    (row,) = ledger.records(kinds=["action"])
    assert row["body"]["data"]["status"] == expected and row["ref"] == EXP
    assert row["at"] == T0.isoformat()


def test_voice_is_off_unless_every_setting_is_present(monkeypatch):
    for name in ("DOORLEDGER_VOICE_TO", "DOORLEDGER_CONNECT_INSTANCE_ID",
                 "DOORLEDGER_CONNECT_FLOW_ID", "DOORLEDGER_CONNECT_SOURCE_NUMBER"):
        monkeypatch.delenv(name, raising=False)  # even if a developer exported their .env
    assert default_voice() is None
    monkeypatch.setenv("DOORLEDGER_CONNECT_INSTANCE_ID", "i")
    monkeypatch.setenv("DOORLEDGER_CONNECT_FLOW_ID", "f")
    monkeypatch.setenv("DOORLEDGER_CONNECT_SOURCE_NUMBER", "+15550100")
    assert default_voice() is None  # no destination: never call anyone
    monkeypatch.setenv("DOORLEDGER_VOICE_TO", "+15550111")
    v = default_voice()
    assert v is not None and v.enabled and v.to == "+15550111"


def test_demo_sms_envelope_names_who_it_was_for():
    hh = demo_household()
    assert demo_envelope(hh.people[0], "Hola") == "[Demo · para Rosa] Hola"
    assert demo_envelope(hh.people[1], "Hi") == "[Demo · for Luis] Hi"
