"""Responder policy: escalation ladder, gaps, caps, closed incidents and message wording."""

from datetime import UTC, datetime, timedelta

import pytest
from doorledger.clock import SimClock
from doorledger.domain import (
    Expectation,
    ExpectationKind,
    Finding,
    FindingKind,
    MedicationProfile,
    Observation,
    ObservationKind,
    Person,
    Severity,
    Source,
)
from doorledger.engine import Engine
from doorledger.household import Household, Patient, demo_household
from doorledger.ledger import Ledger
from doorledger.responder import (
    LADDER_GAP,
    MAX_MESSAGES_PER_INCIDENT,
    Incident,
    Responder,
    TemplateWriter,
)
from doorledger.weather import AmbientTemperature

T0 = datetime(2026, 10, 11, 14, 0, tzinfo=UTC)
EXP = "exp_delivery"
COLD = {"ambient_c": -9.0, "direction": "cold", "minutes_on_porch": 30.0,
        "estimated_internal_c": 1.0, "status": "at_risk"}
HOT = {"ambient_c": 35.0, "direction": "hot", "minutes_on_porch": 145.0,
       "estimated_internal_c": 26.0, "status": "at_risk"}


class Recorder:
    channel = "test"

    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def send(self, person: Person, message: str) -> bool:
        self.sent.append((person.name, message))
        return True


def finding(kind: FindingKind, severity: Severity = Severity.WARNING, data=None,
            exp: str = EXP, summary: str = "Something happened.") -> Finding:
    return Finding(kind, severity, T0, summary, exp, data=dict(COLD if data is None else data))


def make(household: Household | None = None) -> tuple[Responder, Recorder]:
    rec = Recorder()
    return Responder(household or demo_household(), rec, TemplateWriter()), rec


def targets(actions) -> list[str]:
    return [a.target for a in actions]


ROSA, LUIS, ANA = "Rosa Martínez", "Luis (neighbor)", "Ana Martínez (daughter)"
AGENCY = "BrightPath Home Care"


# ------------------------------------------------------------------ porch ladder


def test_at_risk_climbs_patient_neighbor_family():
    r, _ = make()
    f = finding(FindingKind.PACKAGE_AT_RISK)
    # each rung waits LADDER_GAP after the previous message (rules path enforces the gap too)
    steps = [r.handle(f, T0 + LADDER_GAP * i) for i in range(4)]
    assert [targets(s) for s in steps] == [[ROSA], [LUIS], [ANA], []]
    assert r.handle(f, T0 + LADDER_GAP * 1 + timedelta(minutes=1)) == []  # too soon: no skip
    assert [s[0].data["purpose"] for s in steps[:3]] == ["porch_patient", "porch_helper",
                                                         "porch_family"]
    assert r.incidents[EXP].rung == 3 and r.incidents[EXP].messages == 3


def test_followup_respects_ladder_gap():
    r, _ = make()
    f = finding(FindingKind.PACKAGE_AT_RISK)
    assert targets(r.handle(f, T0)) == [ROSA]
    assert r.followup({EXP: f}, T0 + LADDER_GAP - timedelta(seconds=1)) == []
    assert targets(r.followup({EXP: f}, T0 + LADDER_GAP)) == [LUIS]
    assert r.followup({EXP: f}, T0 + LADDER_GAP + timedelta(minutes=5)) == []
    assert targets(r.followup({EXP: f}, T0 + 2 * LADDER_GAP)) == [ANA]
    assert r.followup({EXP: f}, T0 + 5 * LADDER_GAP) == []  # ladder exhausted


def test_followup_ignores_unknown_and_visit_incidents():
    r, _ = make()
    f = finding(FindingKind.PACKAGE_AT_RISK)
    assert r.followup({EXP: f}, T0) == []  # no incident yet
    r.incidents["v"] = Incident("v", "visit", T0, last_at=T0)
    assert r.followup({"v": f}, T0 + LADDER_GAP) == []


def test_family_gets_porch_family_wording():
    r, rec = make()
    f = finding(FindingKind.PACKAGE_AT_RISK)
    for i in range(3):
        r.handle(f, T0 + LADDER_GAP * i)
    to_ana = dict(rec.sent)[ANA]
    assert "nobody nearby has brought it in yet" in to_ana
    assert "in the cold" in to_ana
    assert "Could you bring it inside for her?" in dict(rec.sent)[LUIS]


def test_cap_per_incident():
    hh = demo_household()
    hh.people += [Person(f"Neighbor {i}", "neighbor", escalation_order=2) for i in range(6)]
    r, rec = make(hh)
    f = finding(FindingKind.PACKAGE_AT_RISK)
    sent = r.handle(f, T0)
    for i in range(1, 12):
        sent += r.followup({EXP: f}, T0 + i * LADDER_GAP)
    assert len(sent) == MAX_MESSAGES_PER_INCIDENT
    assert len(rec.sent) == MAX_MESSAGES_PER_INCIDENT
    assert r.incidents[EXP].messages == MAX_MESSAGES_PER_INCIDENT


def test_closed_incident_stops_escalation():
    r, rec = make()
    risk = finding(FindingKind.PACKAGE_AT_RISK)
    r.handle(risk, T0)
    back = finding(FindingKind.PACKAGE_RETRIEVED, Severity.INFO,
                   {**COLD, "status": "safe", "minutes_on_porch": 33.0})
    actions = r.handle(back, T0 + timedelta(minutes=5))
    assert targets(actions) == [ANA]
    assert actions[0].data["purpose"] == "porch_retrieved"
    assert actions[0].message.startswith("Good news")
    assert r.incidents[EXP].closed
    n = len(rec.sent)
    assert r.followup({EXP: risk}, T0 + 3 * LADDER_GAP) == []
    assert r.handle(risk, T0 + 3 * LADDER_GAP) == []
    assert len(rec.sent) == n


def test_retrieved_without_incident_sends_nothing():
    r, rec = make()
    assert r.handle(finding(FindingKind.PACKAGE_RETRIEVED, Severity.INFO), T0) == []
    assert rec.sent == []


@pytest.mark.parametrize("data,expected", [
    (COLD, [ROSA]),
    (HOT, [ROSA]),
    ({**COLD, "ambient_c": 15.0, "direction": "hot"}, []),  # mild day: no nudge
])
def test_package_exposed_nudges_patient_only_on_hot_or_cold_porch(data, expected):
    r, _ = make()
    actions = r.handle(finding(FindingKind.PACKAGE_EXPOSED, Severity.INFO, data), T0)
    assert targets(actions) == expected
    # a second "exposed" never repeats the nudge
    assert r.handle(finding(FindingKind.PACKAGE_EXPOSED, Severity.INFO, data), T0) == []


def test_exposed_then_at_risk_skips_to_neighbor():
    r, _ = make()
    r.handle(finding(FindingKind.PACKAGE_EXPOSED, Severity.INFO), T0)
    assert targets(r.handle(finding(FindingKind.PACKAGE_AT_RISK), T0 + timedelta(minutes=25))) == [LUIS]


# ------------------------------------------------------------------ compromised / visits


def test_compromised_notifies_family_and_patient_and_drafts_pharmacy_claim():
    r, rec = make()
    data = {**COLD, "status": "compromised", "minutes_on_porch": 46.0,
            "estimated_internal_c": -0.5}
    actions = r.handle(finding(FindingKind.PACKAGE_COMPROMISED, Severity.CRITICAL, data), T0)
    assert targets(actions) == [ANA, ROSA, "Pharmacy"]
    claim = actions[-1]
    assert claim.kind == "pharmacy_claim"
    assert claim.delivered is False
    assert claim.data["draft"] is True and claim.data["minutes_on_porch"] == 46.0
    msgs = dict(rec.sent)
    assert "drafted a replacement request for the pharmacy" in msgs[ANA]
    assert "puede que ya no sirva" in msgs[ROSA]  # patient's message is in Spanish


def test_missed_visit_requests_agency_backup_and_tells_family():
    r, rec = make()
    f = finding(FindingKind.MISSED_VISIT, Severity.CRITICAL, {}, exp="exp_visit",
                summary="Maria has not arrived for the 09:00 visit (46 min).")
    actions = r.handle(f, T0)
    assert [(a.kind, a.target) for a in actions] == [("request_backup", AGENCY), ("notify", ANA)]
    assert "Please send a backup aide for Rosa Martínez (Chicago, IL)" in actions[0].message
    assert "asked the agency for a backup" in actions[1].message
    assert r.incidents["exp_visit"].theme == "visit"
    assert len(rec.sent) == 2


def test_late_warning_asks_agency_for_eta_but_late_info_does_not():
    r, _ = make()
    warn = finding(FindingKind.LATE_ARRIVAL, Severity.WARNING, {}, exp="exp_visit",
                   summary="Maria is late for the 09:00 visit.")
    actions = r.handle(warn, T0)
    assert targets(actions) == [AGENCY]
    assert "confirm an ETA" in actions[0].message
    info = finding(FindingKind.LATE_ARRIVAL, Severity.INFO, {}, exp="exp_visit")
    assert r.handle(info, T0) == []


def test_short_visit_goes_to_family_and_agency():
    r, _ = make()
    f = finding(FindingKind.SHORT_VISIT, Severity.WARNING, {}, exp="exp_visit",
                summary="Maria stayed 43 of 120 planned minutes.")
    actions = r.handle(f, T0)
    assert targets(actions) == [ANA, AGENCY]
    assert all("flagged for review" in a.message for a in actions)


@pytest.mark.parametrize("kind", [FindingKind.ON_TIME, FindingKind.VISIT_COMPLETED,
                                  FindingKind.DELIVERY_OVERDUE])
def test_informational_findings_do_nothing(kind):
    r, rec = make()
    assert r.handle(finding(kind, Severity.INFO, {}), T0) == []
    assert rec.sent == []


# ------------------------------------------------------------------ language + guardrails


def test_language_propagates_to_action_data_and_spanish_template():
    r, _ = make()
    f = finding(FindingKind.PACKAGE_AT_RISK)
    to_rosa = r.handle(f, T0)[0]
    assert to_rosa.data["language"] == "es"
    assert to_rosa.data["role"] == "patient"
    assert to_rosa.data["channel"] == "sms"  # household config: Rosa uses no app
    assert to_rosa.data["via"] == "test"  # what actually carried it
    assert to_rosa.data["writer"] == "template"
    assert to_rosa.message.startswith("Hola Rosa")
    assert "está helando" in to_rosa.message and "(-9°C)" in to_rosa.message
    to_luis = r.handle(f, T0 + LADDER_GAP)[0]
    assert to_luis.data["language"] == "en"
    assert "Hola" not in to_luis.message


def test_spanish_hot_porch_template():
    hh = demo_household()
    msg = TemplateWriter().write(finding(FindingKind.PACKAGE_EXPOSED, data=HOT), hh.people[0], hh,
                                 "porch_patient")
    assert "hace mucho calor" in msg and "(35°C)" in msg


def test_spanish_falls_back_to_english_for_untranslated_purpose():
    hh = demo_household()
    msg = TemplateWriter().write(finding(FindingKind.PACKAGE_AT_RISK), hh.people[0], hh,
                                 "porch_helper")
    assert msg.startswith("Rosa's refrigerated medication")


def test_english_patient_template():
    hh = Household("hh", Patient("Tom Smith", 80, "Austin, TX", "America/Chicago"),
                   [Person("Tom Smith", "patient", escalation_order=1)])
    msg = TemplateWriter().write(finding(FindingKind.PACKAGE_AT_RISK, data=HOT), hh.people[0], hh,
                                 "porch_patient")
    assert msg.startswith("Hi Tom") and "warm outside (35°C)" in msg


def test_allowed_rejects_people_outside_household():
    r, _ = make()
    inc = Incident(EXP, "porch", T0)
    stranger = Person("Stranger", "family")
    assert not r.allowed(inc, stranger, T0)
    assert r.allowed(inc, r.household.people[0], T0)
    inc.closed = True
    assert not r.allowed(inc, r.household.people[0], T0)


def test_retrieved_but_compromised_is_not_good_news():
    r, _ = make()
    r.handle(finding(FindingKind.PACKAGE_AT_RISK), T0)
    bad = finding(FindingKind.PACKAGE_RETRIEVED, Severity.CRITICAL,
                  {**COLD, "status": "compromised", "minutes_on_porch": 50.0,
                   "estimated_internal_c": -1.2})
    actions = r.handle(bad, T0 + timedelta(minutes=50))
    assert not any(a.message.startswith("Good news") for a in actions)
    assert any(a.kind == "pharmacy_claim" for a in actions)


# ------------------------------------------------------------------ engine wiring
# (Engine = reconcile + dedupe + responder + ledger; tested here because its job is deciding
# which findings reach the responder and when the ladder is climbed.)


DAY = datetime(2026, 10, 11, tzinfo=UTC)


def t(hh: int, mm: int = 0) -> datetime:
    return DAY.replace(hour=hh, minute=mm)


def make_engine(ambient_c: float = -9.0, start: datetime | None = None):
    hh = demo_household()
    rec = Recorder()
    ledger = Ledger(":memory:", household=hh.id)
    engine = Engine(hh, ledger, Responder(hh, rec, TemplateWriter()),
                    SimClock(start or t(14), speed=0),
                    AmbientTemperature(hh.lat, hh.lon, override_c=ambient_c))
    return engine, rec


def med_delivery() -> Expectation:
    return Expectation(ExpectationKind.MEDICATION_DELIVERY, "Insulin refill", t(13), t(17),
                       medication=MedicationProfile())


def care_visit() -> Expectation:
    return Expectation(ExpectationKind.CAREGIVER_VISIT, "Morning care", t(9), t(11),
                       caregiver="Maria", planned_minutes=120, visit_id="V-MORNING")


def findings(engine) -> list[tuple[str, str]]:
    return [(r["subtype"], r["body"]["severity"]) for r in engine.ledger.records(kinds=["finding"])]


def action_targets(engine) -> list[str]:
    return [r["body"]["target"] for r in engine.ledger.records(kinds=["action"])]


def test_engine_dedupes_by_expectation_kind_severity():
    engine, rec = make_engine()
    engine.add_expectation(med_delivery())
    engine.ingest(Observation(ObservationKind.PACKAGE_DROPPED, t(14), Source.SIMULATED))
    for _ in range(3):
        engine.evaluate(t(14, 5))
    assert findings(engine) == [("package_exposed", "info")]
    assert [name for name, _ in rec.sent] == [ROSA]  # one nudge, not one per evaluate


def test_engine_records_late_warning_and_late_info():
    engine, rec = make_engine(start=t(9, 20))
    v = care_visit()
    engine.add_expectation(v)
    engine.evaluate()
    engine.evaluate()
    engine.clock.set(t(9, 22), 0)
    ci = Observation(ObservationKind.PRESENCE_CHECK_IN, t(9, 22), Source.SIMULATED,
                     visit_id="V-MORNING")
    engine.ingest(ci)
    assert findings(engine) == [("late_arrival", "warning"), ("late_arrival", "info")]
    assert [name for name, _ in rec.sent] == [AGENCY]  # ETA request only for the warning
    # the observation is linked to the visit's expectation in the ledger
    (o,) = engine.ledger.records(kinds=["observation"])
    assert o["ref"] == v.id


def test_engine_followup_climbs_ladder_over_time():
    engine, rec = make_engine(ambient_c=-9.0)
    exp = med_delivery()
    engine.add_expectation(exp)
    engine.ingest(Observation(ObservationKind.PACKAGE_DROPPED, t(14), Source.SIMULATED))
    assert [n for n, _ in rec.sent] == [ROSA]           # exposed on a freezing porch
    engine.evaluate(t(14, 25))                           # at_risk (14.8 min to freezing)
    assert [n for n, _ in rec.sent] == [ROSA, LUIS]
    engine.evaluate(t(14, 30))                           # only 5 min since Luis
    assert [n for n, _ in rec.sent] == [ROSA, LUIS]
    engine.evaluate(t(14, 35))                           # LADDER_GAP elapsed -> family
    assert [n for n, _ in rec.sent] == [ROSA, LUIS, ANA]
    engine.evaluate(t(14, 46))                           # frozen -> compromised
    assert [n for n, _ in rec.sent] == [ROSA, LUIS, ANA, ANA, ROSA]
    assert action_targets(engine)[-1] == "Pharmacy"
    assert findings(engine) == [("package_exposed", "info"), ("package_at_risk", "warning"),
                                ("package_compromised", "critical")]
    assert engine.responder.incidents[exp.id].messages == MAX_MESSAGES_PER_INCIDENT


def test_engine_retrieval_closes_incident():
    engine, rec = make_engine(ambient_c=-9.0)
    engine.add_expectation(med_delivery())
    engine.ingest(Observation(ObservationKind.PACKAGE_DROPPED, t(14), Source.SIMULATED))
    engine.evaluate(t(14, 25))
    engine.clock.set(t(14, 33), 0)
    engine.ingest(Observation(ObservationKind.PACKAGE_REMOVED, t(14, 33), Source.SIMULATED))
    assert [n for n, _ in rec.sent] == [ROSA, LUIS, ANA]
    assert rec.sent[-1][1].startswith("Good news")
    engine.evaluate(t(15, 30))
    assert len(rec.sent) == 3
    assert findings(engine)[-1] == ("package_retrieved", "info")


def test_engine_reset_clears_state():
    engine, rec = make_engine()
    engine.add_expectation(med_delivery())
    engine.ingest(Observation(ObservationKind.PACKAGE_DROPPED, t(14), Source.SIMULATED))
    engine.evaluate(t(14, 25))
    assert engine.ledger.records() and engine.responder.incidents
    engine.reset()
    assert engine.expectations == {} and engine.observations == []
    assert engine._seen == set() and engine.responder.incidents == {}
    assert engine.ledger.records() == []
    # replaying the same story after a reset produces the findings again
    rec.sent.clear()
    engine.add_expectation(med_delivery())
    engine.ingest(Observation(ObservationKind.PACKAGE_DROPPED, t(14), Source.SIMULATED))
    assert findings(engine) == [("package_exposed", "info")]
    assert [n for n, _ in rec.sent] == [ROSA]


def test_engine_state_view():
    engine, _ = make_engine()
    engine.add_expectation(med_delivery())
    engine.add_expectation(care_visit())
    engine.ingest(Observation(ObservationKind.PACKAGE_DROPPED, t(14), Source.SIMULATED))
    s = engine.state(t(14, 10))
    assert s["now"] == t(14, 10).isoformat()
    assert len(s["visits"]) == 1 and s["visits"][0]["check_in"] is None
    (d,) = s["deliveries"]
    assert d["estimate"]["minutes_on_porch"] == 10.0 and d["estimate"]["direction"] == "cold"
    assert {f["kind"] for f in s["findings"]} >= {"package_exposed"}


def test_channel_follows_household_config_never_app_for_rosa():
    """Review 03 §3.4: Rosa (no apps) was shown an "App alert" because the action recorded the
    console notifier's channel. The household decides the channel; ``via`` records the carrier."""
    from doorledger.notify import ConsoleNotifier

    hh = demo_household()
    r = Responder(hh, ConsoleNotifier(), TemplateWriter())
    f = finding(FindingKind.PACKAGE_AT_RISK)
    actions = [*r.handle(f, T0), *r.handle(f, T0 + LADDER_GAP), *r.handle(f, T0 + 2 * LADDER_GAP)]
    by_role = {a.data["role"]: a.data for a in actions}
    assert by_role["patient"]["channel"] == "sms"
    assert by_role["neighbor"]["channel"] == "sms"
    assert by_role["family"]["channel"] == "push"
    assert all(a.data["via"] == "app" for a in actions)  # console: nothing left the machine
    api_people = {p["role"]: p["channel"] for p in hh.to_api()["people"]}
    assert api_people["patient"] == "sms"
