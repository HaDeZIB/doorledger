"""CareAgent tools and guardrails against a populated Engine (no network).

The live test at the bottom calls Bedrock and only runs with DOORLEDGER_LIVE=1.
"""

import json
import os
from datetime import datetime, time
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from doorledger import agent as agent_mod
from doorledger.agent import CareAgent, CareTools, replay_scenario
from doorledger.clock import SimClock
from doorledger.domain import (
    ExpectationKind,
    Finding,
    FindingKind,
    Observation,
    ObservationKind,
    Severity,
    Source,
    utcnow,
)
from doorledger.engine import Engine
from doorledger.household import demo_household
from doorledger.ledger import Ledger
from doorledger.responder import MAX_MESSAGES_PER_INCIDENT, Responder, TemplateWriter
from doorledger.scenarios import day_plan
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


def at(hh, mm):
    return datetime.combine(DAY.date(), time(hh, mm), tzinfo=TZ)


def make_engine(ambient=-9.0):
    hh = demo_household()
    notifier = Recorder()
    eng = Engine(hh, Ledger(household=hh.id), Responder(hh, notifier, TemplateWriter()),
                 SimClock(utcnow(), 0.0), AmbientTemperature(hh.lat, hh.lon, override_c=ambient))
    return eng, notifier


def set_now(eng, dt, evaluate=True):
    eng.clock.set(dt, 0.0)
    if evaluate:
        eng.evaluate(dt)


def plan(eng, kind):
    for e in day_plan(DAY, TZ):
        if e.kind == kind:
            eng.add_expectation(e)
            return e
    raise AssertionError(kind)


@pytest.fixture
def full_day():
    eng, notifier = make_engine()
    replay_scenario(eng, "full_day", DAY)
    return eng, CareTools(eng), notifier


# -- read-only tools ----------------------------------------------------------------------


def test_today_status_is_grounded(full_day):
    _eng, tools, _ = full_day
    s = json.loads(tools.get_today_status())
    assert s["now"] == "14:55" and s["date"] == "2026-10-11"
    (v,) = s["visits"]
    assert v["caregiver"] == "Maria" and v["status"] == "completed"
    assert v["check_in"]["time"] == "09:22" and v["check_out"]["time"] == "10:05"
    assert v["minutes_on_site"] == 43 and v["planned_minutes"] == 120
    assert v["minutes_after_window_start"] == 22
    assert v["check_in"]["source"] == "simulated event"  # until own footage replaces it
    (d,) = s["deliveries"]
    assert d["dropped"]["time"] == "14:07" and d["brought_inside"]["time"] == "14:40"
    assert d["dropped"]["source"] == "simulated event"  # no perception in offline replay
    assert d["exposure_estimate"]["minutes_on_porch"] == 33.0
    assert "estimate" in d["exposure_estimate"]["note"]
    assert d["exposure_estimate"]["assessment"] == "estimate stayed within tolerance; likely fine"
    assert d["fridge_range_c"] == [2.0, 8.0] and d["never_above_c"] == 30.0
    kinds = [f["kind"] for f in s["findings"]]
    assert "short_visit" in kinds and "package_at_risk" in kinds
    luis = [a for a in s["actions"] if a["to"] == "Luis (neighbor)"]
    assert luis and luis[0]["time"] == "14:27" and "porch" in luis[0]["because"]
    assert all(a["decided_by"] == "rules" for a in s["actions"])
    assert len(tools.get_today_status()) < 6000  # compact enough for a cheap model


def test_timeline_filters_by_local_hour(full_day):
    _, tools, _ = full_day
    all_day = json.loads(tools.get_timeline(since_hour=0))["entries"]
    afternoon = json.loads(tools.get_timeline(since_hour=13))["entries"]
    assert all_day[0]["time"] == "09:16"
    assert afternoon and all(e["time"] >= "13:00" for e in afternoon)
    assert len(afternoon) < len(all_day)
    # offline replay has no perception, so the drop is the labelled scripted fallback
    assert any(e["what"] == "observed package_dropped" and e["source"] == "simulated event"
               for e in afternoon)


def test_export_evv(full_day):
    _, tools, _ = full_day
    (row,) = json.loads(tools.export_evv())["rows"]
    assert row["provider"] == "Maria" and row["status"] == "short"
    assert row["time_in"] == "09:22" and row["time_out"] == "10:05"


# -- guardrails ---------------------------------------------------------------------------


def test_notify_refuses_outsider(full_day):
    _eng, tools, notifier = full_day
    before = len(notifier.sent)
    r = json.loads(tools.notify("Dr. Smith", "hello", "test"))
    assert r["sent"] is False and "not in this household" in r["refused"]
    assert len(notifier.sent) == before


def test_notify_refuses_caregiver_and_wrong_role_for_visit_incident(full_day):
    eng, tools, notifier = full_day
    # After full_day only the visit incident is open (the porch one closed at 15:26).
    open_ = [k for k, i in eng.responder.incidents.items() if not i.closed]
    assert len(open_) == 1 and eng.responder.incidents[open_[0]].theme == "visit"
    r = json.loads(tools.notify("Maria (BrightPath)", "hi", "test"))
    assert r["sent"] is False and "agency" in r["refused"]
    r = json.loads(tools.notify("Luis (neighbor)", "hi", "test"))
    assert r["sent"] is False and "only the agency and family" in r["refused"]
    r = json.loads(tools.notify("Ana Martínez (daughter)", "Visit was short today.", "test"))
    assert r["sent"] is True
    assert notifier.sent[-1] == ("Ana Martínez (daughter)", "Visit was short today.")
    last = eng.ledger.records(kinds=["action"])[-1]["body"]
    assert last["data"]["origin"] == "agent" and last["data"]["reason"] == "test"


def test_notify_without_incident_is_refused():
    eng, notifier = make_engine()
    plan(eng, ExpectationKind.CAREGIVER_VISIT)
    set_now(eng, at(9, 5))  # on time so far: no finding, no incident
    r = json.loads(CareTools(eng).notify("Ana Martínez (daughter)", "hi", "test"))
    assert r["sent"] is False and "no open incident" in r["refused"]
    assert notifier.sent == []


def test_porch_ladder_order_gap_and_cap():
    eng, notifier = make_engine()
    e = plan(eng, ExpectationKind.MEDICATION_DELIVERY)
    eng.clock.set(at(14, 7), 0.0)
    eng.ingest(Observation(ObservationKind.PACKAGE_DROPPED, at(14, 7), Source.RING_LIVE))
    assert notifier.sent[-1][0] == "Rosa Martínez"  # rules nudged the patient (rung 1)
    tools = CareTools(eng)
    tools.active_incident = e.id

    set_now(eng, at(14, 10), evaluate=False)
    r = json.loads(tools.notify("Ana Martínez (daughter)", "x", "skip ahead"))
    assert r["sent"] is False and "in order" in r["refused"] and "Luis" in r["refused"]
    r = json.loads(tools.notify("Luis (neighbor)", "x", "too soon"))
    assert r["sent"] is False and "wait until 14:17" in r["refused"]
    r = json.loads(tools.notify("BrightPath Home Care", "x", "agency"))
    assert r["sent"] is False and "escalation ladder" in r["refused"]

    set_now(eng, at(14, 20), evaluate=False)
    r = json.loads(tools.notify("Luis (neighbor)", "Could you bring Rosa's insulin in?", "rung 2"))
    assert r["sent"] is True and eng.responder.incidents[e.id].rung == 2
    r = json.loads(tools.notify("Luis (neighbor)", "again?", "nag"))
    assert r["sent"] is False and "already messaged" in r["refused"]

    eng.responder.incidents[e.id].messages = MAX_MESSAGES_PER_INCIDENT
    r = json.loads(tools.notify("Rosa Martínez", "x", "cap"))
    assert r["sent"] is False and "cap" in r["refused"]


def test_pharmacy_draft_only_when_compromised():
    eng, _ = make_engine()
    e = plan(eng, ExpectationKind.MEDICATION_DELIVERY)
    eng.clock.set(at(14, 7), 0.0)
    eng.ingest(Observation(ObservationKind.PACKAGE_DROPPED, at(14, 7), Source.RING_LIVE,
                           evidence_path="evidence/package.jpg"))
    tools = CareTools(eng)
    set_now(eng, at(14, 15), evaluate=False)
    r = json.loads(tools.draft_pharmacy_replacement(e.id))
    assert r["drafted"] is False and "'safe'" in r["refused"]
    r = json.loads(tools.draft_pharmacy_replacement("exp_nope"))
    assert r["drafted"] is False
    set_now(eng, at(15, 0), evaluate=False)  # ~53 min at -9 °C -> estimated below freezing
    r = json.loads(tools.draft_pharmacy_replacement(e.id))
    assert r["drafted"] is True and r["sent"] is False and "evidence/package.jpg" in r["draft"]
    again = json.loads(tools.draft_pharmacy_replacement(e.id))
    assert again["already_drafted"] is True


def test_backup_aide_guardrails():
    eng, _notifier = make_engine()
    plan(eng, ExpectationKind.CAREGIVER_VISIT)
    set_now(eng, at(9, 20))  # late -> visit incident opened by rules (agency asked for ETA)
    tools = CareTools(eng)
    r = json.loads(tools.request_backup_aide("Maria has not arrived for the 09:00 visit."))
    assert r["sent"] is True and r["to"] == "BrightPath Home Care"
    r = json.loads(tools.request_backup_aide("again"))
    assert r["sent"] is False and "already requested" in r["refused"]


def test_backup_aide_refused_for_porch_incident():
    eng, _ = make_engine()
    e = plan(eng, ExpectationKind.MEDICATION_DELIVERY)
    eng.clock.set(at(14, 7), 0.0)
    eng.ingest(Observation(ObservationKind.PACKAGE_DROPPED, at(14, 7), Source.RING_LIVE))
    tools = CareTools(eng)
    tools.active_incident = e.id
    r = json.loads(tools.request_backup_aide("x"))
    assert r["sent"] is False and "caregiver-visit" in r["refused"]


# -- agent plumbing (fake model, no network) ----------------------------------------------


class FakeResult:
    def __init__(self, text):
        self.message = {"role": "assistant",
                        "content": [{"text": f"<thinking>plan</thinking>{text}"}]}

        self.metrics = SimpleNamespace(
            accumulated_usage={"inputTokens": 10, "outputTokens": 5, "totalTokens": 15},
            cycle_count=2)


def test_model_fallback_and_tool_call_capture(monkeypatch, full_day):
    eng, _, _ = full_day
    tried = []

    class FakeAgent:
        def __init__(self, model, tools, system_prompt, **kw):
            self.model_id = model.config["model_id"]
            self.tools = tools
            self.messages = []

        def __call__(self, prompt, limits=None):
            tried.append(self.model_id)
            if "anthropic" in self.model_id:
                raise RuntimeError("Model use case details have not been submitted for this account")
            out = self.tools[0]()  # get_today_status
            self.messages = [
                {"role": "user", "content": [{"text": prompt}]},
                {"role": "assistant", "content": [
                    {"toolUse": {"toolUseId": "t1", "name": "get_today_status", "input": {}}}]},
                {"role": "user", "content": [
                    {"toolResult": {"toolUseId": "t1", "content": [{"text": out}]}}]},
            ]
            return FakeResult("Maria checked in at 09:22.")

    monkeypatch.setattr(agent_mod, "Agent", FakeAgent)
    monkeypatch.setattr(agent_mod, "_UNAVAILABLE", set())
    ca = CareAgent(eng, models=[agent_mod.CLAUDE_HAIKU, agent_mod.NOVA_PRO])
    reply = ca.ask("Did Maria come today?")
    assert reply.model == agent_mod.NOVA_PRO
    assert reply.text == "Maria checked in at 09:22."  # <thinking> stripped
    assert reply.tool_calls == [{"name": "get_today_status", "input": {}}]
    assert reply.usage["total_tokens"] == 15
    # Claude is remembered as unavailable: the second call goes straight to Nova.
    ca.daily_summary()
    assert tried == [agent_mod.CLAUDE_HAIKU, agent_mod.NOVA_PRO, agent_mod.NOVA_PRO]


def test_ask_gets_read_only_tools(monkeypatch, full_day):
    eng, _, _ = full_day
    seen = {}

    class FakeAgent:
        def __init__(self, model, tools, system_prompt, **kw):
            seen["tools"] = [t.tool_name for t in tools]
            self.messages = []

        def __call__(self, prompt, limits=None):
            return FakeResult("ok")

    monkeypatch.setattr(agent_mod, "Agent", FakeAgent)
    CareAgent(eng, models=["m"]).ask("Text Luis to check on mom")
    assert set(seen["tools"]) == {"get_today_status", "get_timeline", "export_evv"}
    CareAgent(eng, models=["m"]).handle(Finding(FindingKind.SHORT_VISIT, Severity.WARNING,
                                                at(10, 5), "short", "exp_x"))
    assert "notify" in seen["tools"] and "request_backup_aide" in seen["tools"]


# -- live (Bedrock) -----------------------------------------------------------------------


@pytest.mark.skipif(os.environ.get("DOORLEDGER_LIVE") != "1", reason="set DOORLEDGER_LIVE=1")
def test_live_ask(full_day):
    eng, _, _ = full_day
    reply = CareAgent(eng).ask("Did Maria come today, and how long did she stay?")
    assert reply.tool_calls, "agent should ground its answer in a tool call"
    assert "09:22" in reply.text or "9:22" in reply.text
    assert "43" in reply.text


def test_simulated_observations_are_marked_unverified(full_day):
    """Regression (review-03): the agent narrated a QR check-in for a simulated event."""
    _, tools, _ = full_day
    s = json.loads(tools.get_today_status())
    cin = s["visits"][0]["check_in"]
    assert cin["verified"] is False and "simulated" in cin["note"]
    assert "method" not in cin and "evidence" not in cin
