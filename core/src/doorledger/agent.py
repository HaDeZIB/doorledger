"""CareAgent: a Strands Agents layer on top of the deterministic engine.

What the agent may do
---------------------
* **Answer** family questions ("Did Maria come today?") and write the end-of-day summary,
  grounded ONLY in tool output read from the engine and the append-only ledger.
* **Act** (optional ``handle`` mode) by choosing a tool for a finding. Every outbound tool call
  goes through the same guardrails as the deterministic ``Responder``: the person must be in
  the household, the incident must exist and be open, the per-incident cap holds, and the
  escalation ladder is climbed in order with a minimum gap. A refusal is returned to the model
  as a tool result that explains why, so it can pick something else.

What the agent may NOT do
-------------------------
Decide whether a visit happened or whether medication is safe. Those come from
``reconcile.reconcile`` (deterministic) and ``exposure.estimate`` (a documented model). The
agent only reads them. ``ask`` and ``daily_summary`` get read-only tools, so a question typed
into the family app can never trigger an outbound message.

Model choice: Claude Haiku 4.5 on Bedrock when the account has access, else Amazon Nova.
A model that fails with an access/use-case error is skipped for the rest of the process.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from strands import Agent, tool
from strands.models import BedrockModel

from . import evv
from .domain import Action, Finding, FindingKind, Person, Severity
from .engine import Engine
from .notify import channel_fields
from .reconcile import reconcile
from .responder import (
    FIXED_WORDING_ROLES,
    LADDER_GAP,
    MAX_MESSAGES_PER_INCIDENT,
    Incident,
    rung_gap,
)

log = logging.getLogger("doorledger.agent")

CLAUDE_HAIKU = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
NOVA_PRO = "us.amazon.nova-pro-v1:0"
NOVA_2_LITE = "us.amazon.nova-2-lite-v1:0"
NOVA_LITE = "us.amazon.nova-lite-v1:0"

# Models the account cannot use (e.g. Anthropic "use case details have not been submitted").
_UNAVAILABLE: set[str] = set()
_ACCESS_ERRORS = ("use case", "AccessDenied", "not authorized", "ResourceNotFound",
                  "model identifier is invalid", "don't have access", "is not supported")

SOURCE_LABEL = {
    "ring_live_view": "Ring doorbell camera (live view)",
    "ring_snapshot": "Ring doorbell snapshot",
    "ring_webhook": "Ring doorbell event",
    "own_footage": "caregiver's signed presence code read at the door (own footage, not Ring)",
    "simulated": "simulated event",
}


# Deterministic wording for the exposure model's status, so the LLM never grades safety itself.
EXPOSURE_ASSESSMENT = {
    "safe": "estimate stayed within tolerance; likely fine",
    "at_risk": ("estimate came close to the heat limit; probably usable but worth confirming with "
                "the pharmacist"),
    "compromised": "estimate crossed the heat limit; may not be safe, ask the pharmacist",
}


def default_models() -> list[str]:
    """Candidate model ids, best first. ``DOORLEDGER_AGENT_MODEL`` pins the first choice."""
    pinned = os.environ.get("DOORLEDGER_AGENT_MODEL")
    order = [CLAUDE_HAIKU, NOVA_PRO]
    if pinned:
        order = [pinned] + [m for m in order if m != pinned]
    return order


# ---------------------------------------------------------------------------------------
# Tools (pure functions over the engine; no network). Bound as methods so one instance =
# one household. Each returns a JSON string so the model sees exactly what we log.
# ---------------------------------------------------------------------------------------


class CareTools:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.tz = ZoneInfo(engine.household.patient.timezone)
        self.active_incident: str | None = None  # set by CareAgent.handle()
        self.active_finding: Finding | None = None

    # -- helpers --------------------------------------------------------------------

    def _local(self, iso_or_dt: str | datetime | None) -> str | None:
        if iso_or_dt is None:
            return None
        dt = datetime.fromisoformat(iso_or_dt) if isinstance(iso_or_dt, str) else iso_or_dt
        return dt.astimezone(self.tz).strftime("%H:%M")

    def _now(self) -> datetime:
        return self.engine.clock.now()

    def _obs(self, o: dict[str, Any] | None) -> dict[str, Any] | None:
        if not o:
            return None
        out = {"time": self._local(o["at"]), "source": SOURCE_LABEL.get(o["source"], o["source"])}
        if o["source"] == "simulated":
            # Never let the model narrate a verification method for a scripted demo event.
            out["verified"] = False
            out["note"] = "simulated demo event: no camera evidence, not verified"
            return out
        out["verified"] = True
        if o.get("evidence_path"):
            out["evidence"] = o["evidence_path"]
        if o.get("detail", {}).get("method"):
            out["method"] = o["detail"]["method"]
        return out

    def _ref_finding(self, finding_id: str | None) -> dict[str, Any] | None:
        if not finding_id:
            return None
        for rec in self.engine.ledger.records(kinds=["finding"]):
            if rec["id"] == finding_id:
                return rec["body"]
        return None

    def _record_action(self, a: Action, ref: str | None) -> None:
        self.engine.ledger.add_action(a, ref)

    # -- read-only tools ------------------------------------------------------------

    @tool
    def get_today_status(self) -> str:
        """Today's care status at the patient's front door, as compact JSON.

        Includes the household roster, each planned caregiver visit (window, check-in/out
        times with the evidence source), each medication delivery (drop-off/pick-up times
        and the estimated temperature inside the box), deterministic findings, and every
        action DoorLedger already took (who was messaged, when, and why). All times are the
        patient's local time (HH:MM).
        """
        st = self.engine.state()
        hh = self.engine.household
        findings_by_id = {f["id"]: f for f in st["findings"]}
        visits = []
        for v in st["visits"]:
            e = v["expectation"]
            status = ("not_arrived" if not v["check_in"] else
                      "on_site" if not v["check_out"] else "completed")
            late = None
            if v["check_in"]:
                late = round((datetime.fromisoformat(v["check_in"]["at"])
                              - datetime.fromisoformat(e["window_start"])).total_seconds() / 60)
            visits.append({
                "expectation_id": e["id"], "title": e["title"], "caregiver": e["caregiver"],
                "agency": e["agency"],
                "window": f"{self._local(e['window_start'])}-{self._local(e['window_end'])}",
                "planned_minutes": e["planned_minutes"], "status": status,
                "check_in": self._obs(v["check_in"]), "check_out": self._obs(v["check_out"]),
                "minutes_after_window_start": late,
                "minutes_on_site": v["minutes_on_site"],
            })
        deliveries = []
        for d in st["deliveries"]:
            e = d["expectation"]
            est = d["estimate"]
            med = e.get("medication") or {}
            deliveries.append({
                "expectation_id": e["id"], "title": e["title"], "carrier": e["carrier"],
                "medication": (e.get("medication") or {}).get("name"),
                "fridge_range_c": [med.get("store_min_c"), med.get("store_max_c")],
                "never_above_c": med.get("excursion_max_c"),
                "window": f"{self._local(e['window_start'])}-{self._local(e['window_end'])}",
                "dropped": self._obs(d["dropped"]), "brought_inside": self._obs(d["removed"]),
                "exposure_estimate": None if not est else {
                    "minutes_on_porch": est["minutes_on_porch"],
                    "ambient_c": est["ambient_c"],
                    "estimated_internal_c": est["estimated_internal_c"],
                    "status": est["status"],
                    "assessment": EXPOSURE_ASSESSMENT.get(est["status"], est["status"]),
                    "note": "model estimate (no thermometer in the box)",
                },
            })
        findings = [{"time": self._local(f["at"]), "kind": f["kind"], "severity": f["severity"],
                     "summary": f["summary"], "expectation_id": f["expectation_id"]}
                    for f in st["findings"]]
        actions = []
        for a in st["actions"]:
            because = findings_by_id.get(a.get("finding_id"))
            actions.append({
                "time": self._local(a["at"]), "kind": a["kind"], "to": a["target"],
                "message": a["message"][:160], "delivered": a["delivered"],
                "channel": a.get("data", {}).get("channel"),
                "purpose": a.get("data", {}).get("purpose"),
                "decided_by": a.get("data", {}).get("origin", "rules"),
                "because": because["summary"] if because else a.get("data", {}).get("reason"),
            })
        return json.dumps({
            "now": self._local(st["now"]),
            "date": datetime.fromisoformat(st["now"]).astimezone(self.tz).date().isoformat(),
            "patient": {"name": hh.patient.name, "age": hh.patient.age},
            "people": [{"name": p.name, "role": p.role} for p in hh.people],
            "visits": visits, "deliveries": deliveries, "findings": findings, "actions": actions,
        }, ensure_ascii=False)

    @tool
    def get_timeline(self, since_hour: int = 0) -> str:
        """Chronological ledger entries for today from a local hour onward, as compact JSON.

        Every entry has a local time, what happened, and its source (camera, presence code,
        rule, message). Use this to answer "when" and "why" questions with exact times.

        Args:
            since_hour: Local hour of day (0-23) to start from. 0 = the whole day.
        """
        now = self._now().astimezone(self.tz)
        since_hour = max(0, min(23, int(since_hour)))
        since = now.replace(hour=since_hour, minute=0, second=0, microsecond=0)
        out = []
        for rec in self.engine.ledger.records(kinds=["observation", "finding", "action"]):
            at = datetime.fromisoformat(rec["at"]).astimezone(self.tz)
            if at < since or at > now:
                continue
            b = rec["body"]
            if rec["kind"] == "observation":
                entry = {"what": f"observed {rec['subtype']}",
                         "source": SOURCE_LABEL.get(b["source"], b["source"])}
                if b.get("evidence_path"):
                    entry["evidence"] = b["evidence_path"]
            elif rec["kind"] == "finding":
                entry = {"what": f"finding {rec['subtype']} ({b['severity']})",
                         "detail": b["summary"], "source": "DoorLedger rules (deterministic)"}
            else:
                entry = {"what": f"{b['kind']} -> {b['target']}", "detail": b["message"][:200],
                         "source": f"DoorLedger {b.get('data', {}).get('origin', 'rules')}"}
            out.append({"time": at.strftime("%H:%M"), **entry})
        return json.dumps({"since": since.strftime("%H:%M"), "entries": out}, ensure_ascii=False)

    @tool
    def export_evv(self) -> str:
        """Electronic Visit Verification rows for today's caregiver visits (21st Century Cures
        Act fields + verification method + evidence), as JSON."""
        r = reconcile(list(self.engine.expectations.values()), self.engine.observations,
                      self._now(), self.engine.ambient, in_sun=self.engine.household.porch_in_sun)
        return json.dumps({"rows": list(evv.rows(r, self.engine.household))}, ensure_ascii=False)

    # -- guardrails -----------------------------------------------------------------

    def _open_incidents(self) -> dict[str, Incident]:
        return {k: i for k, i in self.engine.responder.incidents.items() if not i.closed}

    def _pick_incident(self) -> tuple[Incident | None, str | None]:
        if self.active_incident:
            inc = self.engine.responder.incidents.get(self.active_incident)
            if inc is None:
                return None, "the incident for this finding no longer exists"
            return inc, None
        open_ = self._open_incidents()
        if not open_:
            return None, ("there is no open incident; DoorLedger only contacts people about a "
                          "finding detected by its rules")
        if len(open_) > 1:
            return None, f"several incidents are open ({', '.join(open_)}); act within handle()"
        return next(iter(open_.values())), None

    def check_notify(self, person: Person | None, name: str, inc: Incident | None,
                     now: datetime, *, repeat_check: bool = True) -> str | None:
        """Return a refusal reason, or None if the message is allowed."""
        hh = self.engine.household
        if person is None:
            names = ", ".join(p.name for p in hh.people if p.role != "caregiver")
            return f"'{name}' is not in this household. Allowed recipients: {names}."
        if inc is None:
            return "no incident"
        if not self.engine.responder.allowed(inc, person, now):
            if inc.closed:
                return "this incident is already resolved; no more messages are sent about it"
            if inc.messages >= MAX_MESSAGES_PER_INCIDENT:
                return (f"the per-incident cap of {MAX_MESSAGES_PER_INCIDENT} messages has been "
                        "reached")
            return f"{person.name} may not be contacted"
        if person.role == "caregiver":
            return "caregivers are contacted through their agency, not directly"
        recent = [r for r in self.engine.ledger.records(kinds=["action"], ref=inc.key,
                                                        since=now - LADDER_GAP)
                  if r["body"]["target"] == person.name] if repeat_check else []
        if recent:
            return (f"{person.name} was already messaged about this at "
                    f"{self._local(recent[-1]['at'])}; do not repeat within "
                    f"{int(LADDER_GAP.total_seconds() // 60)} minutes")
        if inc.theme == "visit":
            if person.role not in ("agency", "family"):
                return ("for a visit problem only the agency and family are contacted "
                        f"({', '.join(p.name for p in hh.people if p.role in ('agency', 'family'))})")
            return None
        # porch incident: climb the ladder in order
        ladder = hh.escalation_ladder()
        compromised = self.engine.ledger.has_finding(inc.key, str(FindingKind.PACKAGE_COMPROMISED))
        if compromised and person.role in ("family", "patient"):
            return None
        if person not in ladder:
            return (f"{person.name} is not on the escalation ladder "
                    f"({' -> '.join(p.name for p in ladder)})")
        idx = ladder.index(person)
        if idx > inc.rung:
            nxt = ladder[inc.rung].name if inc.rung < len(ladder) else "nobody"
            return (f"the ladder must be climbed in order; the next person to contact is {nxt} "
                    f"({' -> '.join(p.name for p in ladder)})")
        since = inc.rung_at or inc.last_at
        if idx == inc.rung and inc.rung > 0 and since:
            # same deadline-squeezed gap as the rules (responder.rung_gap)
            f = self._finding_for(inc)
            gap = rung_gap(f.data.get("minutes_until_excursion_max") if f else None,
                           len(ladder) - inc.rung)
            if now - since < gap:
                wait = (since + gap).astimezone(self.tz).strftime("%H:%M")
                return f"too soon to escalate to {person.name}; wait until {wait}"
        return None

    # -- action tools (handle mode only) ---------------------------------------------

    @tool
    def notify(self, person_name: str, message: str, reason: str) -> str:
        """Send a short SMS-style message to one household member about the current incident.

        Guardrails decide whether it is sent: only household members, only about an open
        incident, at most a few messages per incident, and the escalation ladder (patient ->
        neighbor -> family) must be climbed in order. If refused, the result says why.

        Args:
            person_name: Exact name of the household member, as listed in get_today_status.
            message: The message text (max 300 characters, plain English, facts only).
            reason: One sentence explaining why this person is being contacted now.
        """
        now = self._now()
        person = self.engine.household.person(person_name)
        inc, err = self._pick_incident()
        refusal = err or self.check_notify(person, person_name, inc, now)
        if refusal:
            return json.dumps({"sent": False, "refused": refusal})
        assert inc is not None and person is not None
        ladder = self.engine.household.escalation_ladder()
        if inc.theme == "porch" and person in ladder and ladder.index(person) + 1 > inc.rung:
            inc.rung, inc.rung_at = ladder.index(person) + 1, now
            if person.role == "patient":
                inc.patient_at = now
        if person.role in FIXED_WORDING_ROLES:
            return self._notify_fixed(person, inc, now, reason)
        text = message.strip()[:300]
        delivered = self.engine.responder.notifier.send(person, text)
        inc.messages += 1
        inc.last_at = now
        a = Action(kind="notify", target=person.name, message=text, at=now,
                   finding_id=self.active_finding.id if self.active_finding else None,
                   delivered=delivered,
                   data={**channel_fields(person, self.engine.responder.notifier),
                         "purpose": "agent", "role": person.role, "origin": "agent",
                         "reason": reason[:200]})
        self._record_action(a, inc.key)
        return json.dumps({"sent": True, "to": person.name, "delivered": delivered,
                           "messages_this_incident": inc.messages})

    def _finding_for(self, inc: Incident) -> Finding | None:
        """The finding the fixed wording is about: the one being handled, else the latest
        recorded for this incident."""
        if self.active_finding is not None:
            return self.active_finding
        recs = self.engine.ledger.records(kinds=["finding"], ref=inc.key)
        if not recs:
            return None
        b = recs[-1]["body"]
        return Finding(FindingKind(b["kind"]), Severity(b["severity"]),
                       datetime.fromisoformat(b["at"]), b["summary"], b.get("expectation_id"),
                       list(b.get("observation_ids", [])), dict(b.get("data", {})), b["id"])

    def _notify_fixed(self, person: Person, inc: Incident, now: datetime, reason: str) -> str:
        """The patient and the neighbor never get LLM text: the agent decides *whether* to
        contact them; the words (and Rosa's call + SMS) come from wording.py, via the
        responder."""
        finding = self._finding_for(inc)
        if finding is None:
            return json.dumps({"sent": False, "refused": "no finding to describe"})
        responder = self.engine.responder
        compromised = self.engine.ledger.has_finding(inc.key, str(FindingKind.PACKAGE_COMPROMISED))
        purpose = "porch_compromised" if compromised and person.role == "patient" \
            else responder._purpose(person)
        actions = responder.contact("notify", person, finding, purpose, inc, now,
                                    origin="agent", reason=reason[:200], llm_text_discarded=True)
        for a in actions:
            self._record_action(a, inc.key)
        return json.dumps({"sent": bool(actions), "to": person.name,
                           "delivered": any(a.delivered for a in actions),
                           "wording": "fixed template (the LLM's text is not sent to "
                                      f"{person.role}s)",
                           "messages_this_incident": inc.messages})

    @tool
    def request_backup_aide(self, reason: str) -> str:
        """Ask the home-care agency to send a backup aide for a missed or very late visit.

        Only allowed while a visit incident is open, once per incident.

        Args:
            reason: One sentence with the facts (who was expected, when, how late).
        """
        now = self._now()
        inc, err = self._pick_incident()
        if err:
            return json.dumps({"sent": False, "refused": err})
        assert inc is not None
        if inc.theme != "visit":
            return json.dumps({"sent": False,
                               "refused": "a backup aide is only for a caregiver-visit incident"})
        if any(r["body"]["kind"] == "request_backup"
               for r in self.engine.ledger.records(kinds=["action"], ref=inc.key)):
            return json.dumps({"sent": False,
                               "refused": "a backup aide was already requested for this visit"})
        agency = self.engine.household.by_role("agency")
        if not agency:
            return json.dumps({"sent": False, "refused": "no agency on file"})
        # A backup request is a different ask than an ETA ping, so no repeat check here
        # (it is deduplicated per incident above).
        refusal = self.check_notify(agency[0], agency[0].name, inc, now, repeat_check=False)
        if refusal:
            return json.dumps({"sent": False, "refused": refusal})
        hh = self.engine.household
        text = (f"{reason.strip()[:200]} Please send a backup aide for {hh.patient.name} "
                f"({hh.patient.address}) and confirm the arrival time.")
        delivered = self.engine.responder.notifier.send(agency[0], text)
        inc.messages += 1
        inc.last_at = now
        self._record_action(Action(
            kind="request_backup", target=agency[0].name, message=text, at=now,
            finding_id=self.active_finding.id if self.active_finding else None,
            delivered=delivered, data={"purpose": "visit_backup", "role": "agency",
                                       "origin": "agent", "reason": reason[:200]}), inc.key)
        return json.dumps({"sent": True, "to": agency[0].name, "delivered": delivered})

    @tool
    def draft_pharmacy_replacement(self, expectation_id: str) -> str:
        """Draft (do not send) a replacement request to the pharmacy for a medication delivery
        whose estimated exposure is 'compromised'. Attaches the exposure log and evidence.

        Args:
            expectation_id: The delivery's expectation_id from get_today_status.
        """
        e = self.engine.expectations.get(expectation_id)
        if e is None or e.medication is None:
            return json.dumps({"drafted": False,
                               "refused": f"{expectation_id} is not a medication delivery"})
        existing = [r for r in self.engine.ledger.records(kinds=["action"])
                    if r["body"]["kind"] == "pharmacy_claim"
                    and (r["ref"] == expectation_id
                         or r["body"].get("data", {}).get("expectation_id") == expectation_id)]
        if existing:
            return json.dumps({"drafted": True, "already_drafted": True,
                               "at": self._local(existing[0]["at"])})
        r = reconcile(list(self.engine.expectations.values()), self.engine.observations,
                      self._now(), self.engine.ambient, in_sun=self.engine.household.porch_in_sun)
        d = next((d for d in r.deliveries if d.expectation.id == expectation_id), None)
        if d is None or d.estimate is None or d.estimate.status != "compromised":
            status = d.estimate.status if d and d.estimate else "not delivered"
            return json.dumps({"drafted": False, "refused": (
                f"exposure status is '{status}'; a replacement is only drafted when the estimate "
                "is 'compromised'")})
        evidence = [o.evidence_path for o in (d.dropped, d.removed) if o and o.evidence_path]
        body = (f"Replacement request: {e.medication.name} ({e.title}, {e.carrier} "
                f"{e.tracking}) sat on the porch {int(d.estimate.minutes_on_porch)} min at "
                f"{d.estimate.ambient_c:.0f} °C; estimated {d.estimate.estimated_internal_c} °C "
                f"inside the box. Evidence: {', '.join(evidence) or 'none'}.")
        self._record_action(Action(
            kind="pharmacy_claim", target="Pharmacy", message=body, at=self._now(),
            finding_id=self.active_finding.id if self.active_finding else None, delivered=False,
            data={"draft": True, "origin": "agent", "expectation_id": expectation_id,
                  **d.estimate.as_dict()}), expectation_id)
        return json.dumps({"drafted": True, "sent": False, "draft": body})

    @property
    def read_only(self) -> list[Any]:
        return [self.get_today_status, self.get_timeline, self.export_evv]

    @property
    def actions(self) -> list[Any]:
        return [self.notify, self.request_backup_aide, self.draft_pharmacy_replacement]


# ---------------------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------------------

ASK_PROMPT = """You are DoorLedger, a home-care assistant that watches an older adult's front \
door with a Ring doorbell and keeps a care ledger. A family member is asking you \
a question.

Rules:
- ALWAYS call a tool before answering. Use get_today_status first; use get_timeline for exact \
"when"/"why" questions; export_evv for visit-verification records.
- Answer ONLY from tool output. Cite the local time (HH:MM) and the source of each fact (for \
example "Ring doorbell camera" or "presence code shown to the doorbell").
- If the data does not contain the answer, say "I don't know" and say what you can see instead. \
Never guess, never invent people, times or temperatures.
- Temperatures inside a package are model estimates, not measurements; say so. Do not give \
medical advice; if medication may be compromised, suggest checking with the pharmacist.
- Any fact whose source says "simulated" is a demo event with no camera evidence: say it is \
simulated/unverified and never describe how it was verified (no QR, no camera, no code).
- 2-4 short sentences, plain English, no markdown, no emojis."""

SUMMARY_PROMPT = """You are DoorLedger, a home-care assistant. Write the end-of-day summary for \
the patient's family.

Rules:
- Call get_today_status first (and get_timeline if you need exact order of events).
- 4-6 sentences, warm and calm, plain English, no markdown, no lists, no emojis.
- Cover: the caregiver visit (arrival time, time on site vs planned), the medication delivery \
(when it arrived, how long it was outside, estimated temperature, whether it is likely safe), \
and who DoorLedger contacted and why.
- Only mention people who appear in the tool output; say someone was contacted only if they \
appear in actions[].to.
- Use ONLY facts from the tools, with local times. Package temperatures are estimates; say so. \
If something is unknown, say so rather than guessing. Facts whose source is "simulated" are demo \
events without camera evidence: call them simulated/unverified."""

HANDLE_PROMPT = """You are DoorLedger's response agent. A deterministic rule engine detected the \
finding below at the patient's front door. Decide what, if anything, to do with your tools.

Rules:
- Call get_today_status first to see what has already been done. Do not repeat an action.
- Only these tools act in the world: notify, request_backup_aide, draft_pharmacy_replacement.
- Guardrails may refuse a tool call; read the reason and adapt (for example contact the person \
it names), or stop. Never try to work around a refusal.
- Informational findings (on time, delivered, completed) usually need no action.
- Messages: max 300 characters, warm, calm, specific, facts only, no emojis.
- The patient and the neighbor always get DoorLedger's fixed wording (the patient: a call plus \
an SMS in her language); your message text is only used for family and the agency.
- Finish with one sentence describing what you did and why."""


@dataclass
class AgentReply:
    text: str
    model: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    latency_ms: int = 0
    usage: dict[str, int] = field(default_factory=dict)
    cycles: int = 0

    def to_api(self, key: str = "answer") -> dict[str, Any]:
        return {key: self.text, "tool_calls": self.tool_calls, "model": self.model,
                "latency_ms": self.latency_ms, "usage": self.usage}


def _text_of(result: Any) -> str:
    parts = [c.get("text", "") for c in result.message.get("content", []) if "text" in c]
    text = "".join(parts).strip()
    # Nova sometimes wraps chain-of-thought in <thinking>; families should not see it.
    while "<thinking>" in text and "</thinking>" in text:
        a, b = text.index("<thinking>"), text.index("</thinking>") + len("</thinking>")
        text = (text[:a] + text[b:]).strip()
    return text


def _tool_calls(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"name": c["toolUse"]["name"], "input": c["toolUse"].get("input", {})}
            for m in messages if m.get("role") == "assistant"
            for c in m.get("content", []) if "toolUse" in c]


class CareAgent:
    """Strands agent over one household's engine. Each call builds a fresh ``Agent`` (no
    cross-question memory, no concurrency lock contention)."""

    def __init__(self, engine: Engine, models: list[str] | None = None, *,
                 region: str | None = None, max_tokens: int = 700) -> None:
        self.engine = engine
        self.tools = CareTools(engine)
        self.models = models or default_models()
        self.region = region or os.environ.get("AWS_REGION", "us-east-1")
        self.max_tokens = max_tokens
        self.last: AgentReply | None = None

    def _model(self, model_id: str) -> BedrockModel:
        return BedrockModel(model_id=model_id, region_name=self.region,
                            max_tokens=self.max_tokens, temperature=0.0, streaming=False)

    def _run(self, system: str, prompt: str, tools: list[Any], max_turns: int = 6) -> AgentReply:
        last_exc: Exception | None = None
        for model_id in self.models:
            if model_id in _UNAVAILABLE:
                continue
            agent = Agent(model=self._model(model_id), tools=tools, system_prompt=system,
                          callback_handler=None, name="doorledger-care-agent")
            t0 = time.perf_counter()
            try:
                result = agent(prompt, limits={"turns": max_turns})
            except Exception as exc:
                last_exc = exc
                if any(s in str(exc) for s in _ACCESS_ERRORS):
                    log.warning("agent: %s unavailable, skipping (%s)", model_id, str(exc)[:160])
                    _UNAVAILABLE.add(model_id)
                    continue
                raise
            u = result.metrics.accumulated_usage
            reply = AgentReply(
                text=_text_of(result), model=model_id, tool_calls=_tool_calls(agent.messages),
                latency_ms=int((time.perf_counter() - t0) * 1000),
                usage={"input_tokens": u.get("inputTokens", 0),
                       "output_tokens": u.get("outputTokens", 0),
                       "total_tokens": u.get("totalTokens", 0)},
                cycles=result.metrics.cycle_count)
            self.last = reply
            return reply
        raise RuntimeError(f"no Bedrock model available for the agent: {last_exc}")

    # -- capabilities -----------------------------------------------------------------

    def ask(self, question: str) -> AgentReply:
        """Family Q&A grounded in the ledger. Read-only tools only."""
        return self._run(ASK_PROMPT, question.strip()[:500], self.tools.read_only)

    def daily_summary(self) -> AgentReply:
        return self._run(SUMMARY_PROMPT, "Write today's summary for the family.",
                         self.tools.read_only)

    def handle(self, finding: Finding) -> AgentReply:
        """Optional agentic response to one finding. The incident key comes from the finding
        (deterministic), so the agent cannot invent one; guardrails still gate every call."""
        exp = finding.expectation_id or finding.id
        theme = "porch" if str(finding.kind).startswith("package_") else "visit"
        self.engine.responder.incidents.setdefault(exp, Incident(exp, theme, self.engine.clock.now()))
        self.tools.active_incident, self.tools.active_finding = exp, finding
        try:
            prompt = (f"Finding at {self.tools._local(finding.at)}: {finding.kind} "
                      f"({finding.severity}). {finding.summary}\n"
                      f"expectation_id: {finding.expectation_id}\nfacts: {json.dumps(finding.data)}")
            return self._run(HANDLE_PROMPT, prompt, self.tools.read_only + self.tools.actions,
                             max_turns=8)
        finally:
            self.tools.active_incident = self.tools.active_finding = None


# ---------------------------------------------------------------------------------------
# Headless replay helper (tests + spike script): run a scenario minute by minute, no asyncio,
# no perception, no network.
# ---------------------------------------------------------------------------------------


def replay_scenario(engine: Engine, name: str, day: datetime | None = None,
                    step: timedelta = timedelta(minutes=1)) -> None:
    from .domain import Observation
    from .scenarios import SCENARIOS, _at, day_plan

    spec = SCENARIOS[name]
    tz = ZoneInfo(engine.household.patient.timezone)
    day = day or datetime.now(tz)
    engine.reset()
    if hasattr(engine.ambient, "override_c"):
        engine.ambient.override_c = spec["ambient_c"]
    kinds = spec.get("plan")
    for e in day_plan(day, tz):
        if kinds is None or e.kind in kinds:
            engine.add_expectation(e)
    now, end = _at(day, *spec["start"], tz), _at(day, *spec["end"], tz)
    if hasattr(engine.clock, "set"):
        engine.clock.set(now, 0.0)
    pending = sorted(spec["steps"], key=lambda s: (s.hh, s.mm))
    while now <= end:
        if hasattr(engine.clock, "set"):
            engine.clock.set(now, 0.0)
        while pending and _at(day, pending[0].hh, pending[0].mm, tz) <= now:
            s = pending.pop(0)
            engine.ingest(Observation(kind=s.kind, at=_at(day, s.hh, s.mm, tz), source=s.source,
                                      visit_id=s.visit_id, evidence_path=s.evidence,
                                      detail=dict(s.detail), device_id=engine.device.get("id")))
        engine.evaluate(now)
        now += step
    if hasattr(engine.clock, "pause"):
        engine.clock.set(end, 0.0)
        engine.clock.pause()
