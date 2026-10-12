"""Responder: turns findings into actions, with an escalation ladder and hard guardrails.

Two layers:

* ``Policy`` (deterministic) decides WHEN to act and WHO is eligible: the patient first,
  then a neighbor, then family, with minimum gaps between rungs and a per-incident cap.
  Missed visits go to the agency (backup request) and family.
* A ``Writer`` decides HOW to say it. The default writer is an LLM on Bedrock that writes a
  short, calm, specific message for family and agency; if Bedrock is unavailable it falls back
  to templates. The patient and the neighbor always get fixed wording (wording.py): no LLM
  ever writes to the 81-year-old at the door.

The patient's rung (porch incidents), as agreed with the family:

* minute 0: a voice call in Spanish (primary) and an SMS with the same words, sent together;
* +5 min: a second call if Ring has not seen the box picked up;
* then the neighbor and then family, ``LADDER_GAP`` apart, squeezed when the exposure model
  says little time is left before the medication is unsafe (``rung_gap``);
* Ring seeing the pickup closes the incident and cancels every pending step, each logged as a
  ``cancelled`` action. The doorbell is the patient's reply; she never has to answer.

The agent layer (agent.py) can replace the policy's choice of *which* tool to call, but every
tool call still passes through ``Policy.allowed`` — the LLM can never message someone outside
the ladder, exceed the cap, or invent an incident.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from . import wording
from .domain import Action, Finding, FindingKind, Person
from .household import Household
from .notify import ConnectVoiceNotifier, Notifier, channel_fields

log = logging.getLogger("doorledger.responder")

LADDER_GAP = timedelta(minutes=10)  # longest wait on one rung before asking the next person
MIN_GAP = timedelta(minutes=2)  # shortest, when time is nearly out
PATIENT_RECALL = timedelta(minutes=5)  # second call to the patient if the box is still out
# Contacts per incident. A call and the SMS sent with it are one contact.
MAX_MESSAGES_PER_INCIDENT = 6
HOT_PORCH_C = 25.0
COLD_PORCH_C = 5.0
FIXED_WORDING_ROLES = ("patient", "neighbor")  # never written by an LLM


def rung_gap(minutes_left: float | None, rungs_left: int) -> timedelta:
    """How long to wait on the current rung before asking the next person.

    ``LADDER_GAP`` normally; shorter when the exposure model's time left before the medication
    is unsafe would not leave every remaining rung a fair share of it (improvements-04 §1.4).
    """
    if minutes_left is None:
        return LADDER_GAP
    share = timedelta(minutes=max(minutes_left, 0.0) / (rungs_left + 1))
    return max(MIN_GAP, min(LADDER_GAP, share))


@dataclass
class Incident:
    key: str  # expectation id
    theme: str  # porch | visit
    opened_at: datetime
    rung: int = 0  # index into the escalation ladder already notified
    last_at: datetime | None = None
    messages: int = 0  # contacts made (see MAX_MESSAGES_PER_INCIDENT)
    closed: bool = False
    finding_ids: list[str] = field(default_factory=list)
    rung_at: datetime | None = None  # when the current rung was first contacted
    patient_at: datetime | None = None  # first call/SMS to the patient
    recalls: int = 0  # second calls to the patient


class Writer(Protocol):
    def write(self, finding: Finding, recipient: Person, household: Household,
              purpose: str) -> str: ...


class TemplateWriter:
    def write(self, finding: Finding, recipient: Person, household: Household,
              purpose: str) -> str:
        patient = household.patient.name.split()[0]
        d = finding.data
        cold = d.get("direction") == "cold"
        who = wording.People.of(household)
        if recipient.role == "patient":
            fixed = wording.patient_sms(purpose, who, cold, recipient.language)
            if fixed:
                return fixed
        if recipient.role == "neighbor" and purpose == "porch_helper":
            return wording.neighbor_sms(who, cold, int(d.get("minutes_on_porch", 0)),
                                        recipient.language)
        if purpose == "porch_family":
            return (f"{patient}'s refrigerated medication has been outside {int(d.get('minutes_on_porch', 0))} "
                    f"min in the {'cold' if cold else 'heat'} and nobody nearby has brought it in yet. "
                    f"Could you call {patient} or someone close by?")
        if purpose == "porch_compromised":
            return (f"Heads up: {patient}'s medication sat outside ~{int(d.get('minutes_on_porch', 0))} "
                    f"min (est. {d.get('estimated_internal_c', '?')}°C in the box). It may not be safe "
                    f"to use. Please arrange a replacement: I've drafted a replacement request for the "
                    f"pharmacy with the camera evidence. {patient} was told to keep it in the fridge "
                    f"and to call the pharmacy or you before using it.")
        if purpose == "porch_retrieved":
            return (f"Good news: {patient}'s medication was brought inside after "
                    f"{int(d.get('minutes_on_porch', 0))} min (est. {d.get('estimated_internal_c', '?')}°C).")
        if purpose == "visit_backup":
            return (f"{finding.summary} Please send a backup aide for {household.patient.name} "
                    f"({household.patient.address}) and confirm the new arrival time.")
        if purpose == "visit_family":
            return f"{finding.summary} I've asked the agency for a backup and will keep you posted."
        if purpose == "visit_agency_late":
            return f"{finding.summary} Can you confirm an ETA for {household.patient.name}'s visit?"
        if purpose == "visit_short":
            return f"{finding.summary} The visit record has been flagged for review."
        return finding.summary


class BedrockWriter:
    """Writes each message with an LLM; strictly grounded in the finding's numbers."""

    SYSTEM = (
        "You write SMS-length messages (max 300 characters) for DoorLedger, a home-care assistant "
        "that watches an older adult's front door. Be warm, calm and specific. Use ONLY the facts "
        "provided; never invent times, temperatures or names. No emojis, no markdown. Write in the "
        "language requested for the recipient; for Spanish use simple, respectful Mexican Spanish "
        "with 'usted'."
    )

    def __init__(self, model_id: str | None = None, fallback: Writer | None = None) -> None:
        import boto3

        primary = model_id or os.environ.get(
            "DOORLEDGER_WRITER_MODEL", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
        # Try Claude first, then Amazon Nova, then templates — an alert is never blocked.
        self.models = [primary, "us.amazon.nova-lite-v1:0"]
        self.client = boto3.client("bedrock-runtime",
                                   region_name=os.environ.get("AWS_REGION", "us-east-1"))
        self.fallback = fallback or TemplateWriter()

    def write(self, finding: Finding, recipient: Person, household: Household,
              purpose: str) -> str:
        draft = self.fallback.write(finding, recipient, household, purpose)
        if recipient.role in FIXED_WORDING_ROLES:
            # The patient and the neighbor get fixed wording: same shape every time for Rosa,
            # and no health details for Luis that an LLM could pick up from the facts.
            self.last_model = "template"
            return draft
        prompt = (
            f"Recipient: {recipient.name} (role: {recipient.role}).\n"
            f"Write the message in: {'Spanish' if recipient.language == 'es' else 'English'}.\n"
            f"Patient: {household.patient.name}, {household.patient.age}.\n"
            f"Situation ({finding.kind}, {finding.severity}): {finding.summary}\n"
            f"Facts: {finding.data}\n"
            f"Goal of this message: {purpose}.\n"
            f"Reference draft (rewrite naturally, keep every fact): {draft}"
        )
        for model in list(self.models):
            try:
                resp = self.client.converse(
                    modelId=model,
                    system=[{"text": self.SYSTEM}],
                    messages=[{"role": "user", "content": [{"text": prompt}]}],
                    inferenceConfig={"maxTokens": 200, "temperature": 0.3},
                )
                text = "".join(c.get("text", "") for c in resp["output"]["message"]["content"])
                if text.strip():
                    self.last_model = model
                    return text.strip()[:480]
            except Exception as exc:  # noqa: BLE001 - never block an alert on the LLM
                log.warning("writer: %s unavailable (%s)", model, str(exc)[:120])
                if "use case" in str(exc) or "AccessDenied" in str(exc):
                    self.models.remove(model)  # don't retry a model the account can't use yet
        self.last_model = "template"
        return draft


class Responder:
    def __init__(self, household: Household, notifier: Notifier, writer: Writer | None = None,
                 voice: ConnectVoiceNotifier | None = None,
                 on_update: Callable[[Action], None] | None = None):
        self.household = household
        self.notifier = notifier
        self.writer = writer or TemplateWriter()
        self.voice = voice  # None: calls are scripted and shown, but not placed
        self.on_update = on_update  # called when a call's outcome arrives (answered/no answer)
        self.incidents: dict[str, Incident] = {}

    # -- guardrails ----------------------------------------------------------------

    def allowed(self, incident: Incident, person: Person, now: datetime) -> bool:
        if incident.closed or incident.messages >= MAX_MESSAGES_PER_INCIDENT:
            return False
        return person in self.household.people

    # -- one contact: every channel the household set for this person -------------------

    def contact(self, kind: str, person: Person, finding: Finding, purpose: str,
                incident: Incident | None, now: datetime, *,
                channels: list[str | None] | None = None, **extra: Any) -> list[Action]:
        """Reach ``person`` on each of their channels at once (Rosa: call + SMS). Counts as one
        contact against the cap. A call that fails falls back to text when no text was sent."""
        if incident is not None and not self.allowed(incident, person, now):
            return []
        chans = channels or person.contact_channels()
        base = {"purpose": purpose, "role": person.role, "language": person.language, **extra}
        out: list[Action] = []
        texted = False
        for ch in chans:
            if ch == "voice":
                call = self._call(kind, person, finding, purpose, now, base)
                if call is not None:
                    out.append(call)
                continue
            out.append(self._text(kind, person, finding, purpose, now, base, ch))
            texted = True
        if not texted and any(a.data.get("status") == "failed" for a in out):
            sms = next((c for c in person.contact_channels() if c not in (None, "voice")), None)
            out.append(self._text(kind, person, finding, purpose, now,
                                  {**base, "fallback_for": "voice"}, sms or "sms"))
        if out and incident is not None:
            incident.messages += 1
            incident.last_at = now
        return out

    def _text(self, kind: str, person: Person, finding: Finding, purpose: str, now: datetime,
              base: dict[str, Any], channel: str | None) -> Action:
        message = self.writer.write(finding, person, self.household, purpose)
        delivered = self.notifier.send(person, message)
        return Action(kind=kind, target=person.name, message=message, at=now,
                      finding_id=finding.id, delivered=delivered,
                      data={**channel_fields(person, self.notifier, channel), **base,
                            "writer": getattr(self.writer, "last_model", "template")})

    def _call(self, kind: str, person: Person, finding: Finding, purpose: str, now: datetime,
              base: dict[str, Any]) -> Action | None:
        cold = finding.data.get("direction") == "cold"
        script = wording.patient_call(purpose, wording.People.of(self.household), cold,
                                      person.language)
        if script is None:
            return None
        data = {**base, "channel": "voice", "writer": "template", "ssml": script.ssml}
        if self.voice is None:
            # No Amazon Connect configured: the dashboard shows the script, no call is placed.
            data.update(via="app", status="not_placed")
            return Action(kind=kind, target=person.name, message=script.text, at=now,
                          finding_id=finding.id, delivered=False, data=data)
        contact_id = self.voice.call(person, script.ssml)
        if contact_id is None:
            data.update(via="voice", status="failed")
            return Action(kind=kind, target=person.name, message=script.text, at=now,
                          finding_id=finding.id, delivered=False, data=data)
        data.update(via="voice", status="placed", contact_id=contact_id)
        action = Action(kind=kind, target=person.name, message=script.text, at=now,
                        finding_id=finding.id, delivered=True, data=data)
        self.voice.watch(contact_id, lambda status: self._call_outcome(action, status))
        return action

    def _call_outcome(self, action: Action, status: str) -> None:
        action.data["status"] = status  # "answered" | "no_answer"
        if self.on_update:
            self.on_update(action)

    # -- the porch ladder ------------------------------------------------------------

    @staticmethod
    def _purpose(person: Person) -> str:
        return {"patient": "porch_patient", "family": "porch_family"}.get(person.role,
                                                                           "porch_helper")

    def _open_rung(self, inc: Incident, person: Person, finding: Finding,
                   now: datetime) -> list[Action]:
        inc.rung += 1
        inc.rung_at = now
        if person.role == "patient":
            inc.patient_at = now
        return self.contact("notify", person, finding, self._purpose(person), inc, now)

    def _recall(self, inc: Incident, finding: Finding, now: datetime) -> list[Action]:
        """Second call to the patient, once, PATIENT_RECALL after the first."""
        patient = next((p for p in self.household.escalation_ladder() if p.role == "patient"), None)
        if (patient is None or inc.patient_at is None or inc.recalls
                or now - inc.patient_at < PATIENT_RECALL
                or "voice" not in patient.contact_channels()):
            return []
        inc.recalls += 1
        return self.contact("notify", patient, finding, "porch_patient", inc, now,
                            channels=["voice"], attempt=2)

    def _climb(self, inc: Incident, finding: Finding, now: datetime) -> list[Action]:
        ladder = self.household.escalation_ladder()
        if inc.rung >= len(ladder) or inc.rung_at is None:
            return []
        left = finding.data.get("minutes_until_excursion_max")
        if now - inc.rung_at < rung_gap(left, len(ladder) - inc.rung):
            return []
        return self._open_rung(inc, ladder[inc.rung], finding, now)

    def _stand_down(self, inc: Incident, finding: Finding,
                    told: list[Action] | None = None) -> list[Action]:
        """Ring saw the box picked up: log every step that will no longer happen.

        ``told`` are the messages just sent about the pickup itself (Ana's "Good news" text,
        Rosa's "Listo"). A pending step on a channel that person was just reached on is not
        logged as "not needed": they did get a text, just a different one."""
        tz = ZoneInfo(self.household.patient.timezone)
        local = finding.at.astimezone(tz)
        when = f"{local.hour % 12 or 12}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'}"
        patient = self.household.patient.name.split()[0]
        reason = f"Ring saw the box picked up at {when}. The doorbell is {patient}'s reply."
        ladder = self.household.escalation_ladder()
        pending: list[tuple[Person, str, str]] = []
        first = next((p for p in ladder if p.role == "patient"), None)
        if (first is not None and inc.patient_at is not None and not inc.recalls
                and "voice" in first.contact_channels()):
            pending.append((first, "voice", f"Second call to {patient} not needed"))
        for p in ladder[inc.rung:]:
            ch = p.contact_channels()[0] or "sms"
            verb = {"voice": "Call", "sms": "Text"}.get(ch, "Message")
            pending.append((p, ch, f"{verb} to {p.name.split()[0]} not needed"))
        reached = {(a.target, a.data.get("channel")) for a in told or []}
        pending = [(p, ch, what) for p, ch, what in pending if (p.name, ch) not in reached]
        return [Action(kind="cancelled", target=p.name, message=f"{what}: {reason}",
                       at=finding.at, finding_id=finding.id, delivered=False,
                       data={"channel": ch, "via": "none", "role": p.role,
                             "language": "en", "purpose": "cancelled",
                             "reason": "ring_saw_pickup"})
                for p, ch, what in pending]

    # -- entry points --------------------------------------------------------------

    def handle(self, finding: Finding, now: datetime) -> list[Action]:
        k = finding.kind
        exp = finding.expectation_id or finding.id
        out: list[Action] = []
        ladder = self.household.escalation_ladder()
        family = self.household.by_role("family")
        agency = self.household.by_role("agency")

        if k == FindingKind.PACKAGE_EXPOSED:
            # Medication just landed on a hot or freezing porch: the patient first (call + SMS).
            amb = finding.data.get("ambient_c", 20)
            if (amb >= HOT_PORCH_C or amb <= COLD_PORCH_C) and ladder:
                inc = self.incidents.setdefault(exp, Incident(exp, "porch", now))
                inc.finding_ids.append(finding.id)
                if inc.rung == 0:
                    out += self._open_rung(inc, ladder[0], finding, now)
        elif k == FindingKind.PACKAGE_AT_RISK:
            # Still outside and getting close to unsafe.
            inc = self.incidents.setdefault(exp, Incident(exp, "porch", now))
            inc.finding_ids.append(finding.id)
            if inc.closed:
                pass
            elif inc.rung == 0 and ladder:
                out += self._open_rung(inc, ladder[0], finding, now)
            else:
                out += self._climb(inc, finding, now)
        elif k == FindingKind.PACKAGE_COMPROMISED:
            inc = self.incidents.setdefault(exp, Incident(exp, "porch", now))
            for person in [*family, ladder[0]] if ladder else family:
                out += self.contact("notify", person, finding, "porch_compromised", inc, now)
            out.append(Action(kind="pharmacy_claim", target="Pharmacy", at=now, finding_id=finding.id,
                              message="Replacement request drafted with exposure log and camera evidence.",
                              delivered=False, data={"draft": True, **finding.data}))
        elif k == FindingKind.PACKAGE_RETRIEVED and finding.severity == "critical":
            # Brought inside, but only after the estimate crossed the limit: not good news.
            inc = self.incidents.setdefault(exp, Incident(exp, "porch", now))
            for person in [*family, ladder[0]] if ladder else family:
                out += self.contact("notify", person, finding, "porch_compromised", inc, now)
            out.append(Action(kind="pharmacy_claim", target="Pharmacy", at=now, finding_id=finding.id,
                              message="Replacement request drafted with exposure log and camera evidence.",
                              delivered=False, data={"draft": True, **finding.data}))
            out += self._stand_down(inc, finding, told=out)
            inc.closed = True
        elif k == FindingKind.PACKAGE_RETRIEVED:
            inc = self.incidents.get(exp)
            if inc and not inc.closed:
                inc.closed = True
                for person in family:
                    out += self.contact("notify", person, finding, "porch_retrieved", None, now)
                for person in self.household.by_role("patient"):
                    # Closure for Rosa too, by text only (no call once it is inside).
                    texts = [c for c in person.contact_channels() if c != "voice"]
                    if texts:
                        out += self.contact("notify", person, finding, "porch_retrieved", None,
                                            now, channels=texts)
                out += self._stand_down(inc, finding, told=out)
        elif k == FindingKind.MISSED_VISIT:
            inc = self.incidents.setdefault(exp, Incident(exp, "visit", now))
            for person in agency:
                out += self.contact("request_backup", person, finding, "visit_backup", inc, now)
            for person in family:
                out += self.contact("notify", person, finding, "visit_family", inc, now)
        elif k == FindingKind.LATE_ARRIVAL and finding.severity != "info":
            inc = self.incidents.setdefault(exp, Incident(exp, "visit", now))
            for person in agency:
                out += self.contact("notify", person, finding, "visit_agency_late", inc, now)
        elif k == FindingKind.SHORT_VISIT:
            for person in [*family, *agency]:
                out += self.contact("notify", person, finding, "visit_short", None, now)
        return out

    def followup(self, porch_findings: dict[str, Finding], now: datetime) -> list[Action]:
        """For open porch incidents nobody has resolved yet: the patient's second call, then
        the next rung once its (deadline-squeezed) gap has passed."""
        out: list[Action] = []
        for exp_id, finding in porch_findings.items():
            inc = self.incidents.get(exp_id)
            if not inc or inc.closed or inc.theme != "porch" or inc.rung == 0:
                continue
            out += self._recall(inc, finding, now)
            out += self._climb(inc, finding, now)
        return out
