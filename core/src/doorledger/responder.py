"""Responder: turns findings into actions, with an escalation ladder and hard guardrails.

Two layers:

* ``Policy`` (deterministic) decides WHEN to act and WHO is eligible: the patient first,
  then a neighbor, then family, with minimum gaps between rungs and a per-incident cap.
  Missed visits go to the agency (backup request) and family.
* A ``Writer`` decides HOW to say it. The default writer is an LLM on Bedrock that writes a
  short, calm, specific message; if Bedrock is unavailable it falls back to templates.

The agent layer (agent.py) can replace the policy's choice of *which* tool to call, but every
tool call still passes through ``Policy.allowed`` — the LLM can never message someone outside
the ladder, exceed the cap, or invent an incident.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from .domain import Action, Finding, FindingKind, Person
from .household import Household
from .notify import Notifier

log = logging.getLogger("doorledger.responder")

LADDER_GAP = timedelta(minutes=10)
MAX_MESSAGES_PER_INCIDENT = 5
HOT_PORCH_C = 25.0
COLD_PORCH_C = 5.0


@dataclass
class Incident:
    key: str  # expectation id
    theme: str  # porch | visit
    opened_at: datetime
    rung: int = 0  # index into the escalation ladder already notified
    last_at: datetime | None = None
    messages: int = 0
    closed: bool = False
    finding_ids: list[str] = field(default_factory=list)


class Writer(Protocol):
    def write(self, finding: Finding, recipient: Person, household: Household,
              purpose: str) -> str: ...


class TemplateWriter:
    def write(self, finding: Finding, recipient: Person, household: Household,
              purpose: str) -> str:
        patient = household.patient.name.split()[0]
        d = finding.data
        cold = d.get("direction") == "cold"
        weather = "freezing" if cold else "warm"
        if recipient.language == "es":
            spanish = self._spanish(purpose, patient, d, cold)
            if spanish:
                return spanish
        if purpose == "porch_patient":
            return (f"Hi {patient}, your medication was left at the front door and it's {weather} "
                    f"outside ({d.get('ambient_c', 0):.0f}°C). Please bring it inside and put it in "
                    f"the fridge.")
        if purpose == "porch_helper":
            return (f"{patient}'s refrigerated medication has been on her porch for "
                    f"{int(d.get('minutes_on_porch', 0))} min in the {'cold' if cold else 'heat'} and "
                    f"she hasn't picked it up. Could you bring it inside for her?")
        if purpose == "porch_family":
            return (f"{patient}'s refrigerated medication has been outside {int(d.get('minutes_on_porch', 0))} "
                    f"min in the {'cold' if cold else 'heat'} and nobody nearby has brought it in yet. "
                    f"Could you call {patient} or someone close by?")
        if purpose == "porch_compromised":
            return (f"Heads up: {patient}'s medication sat outside ~{int(d.get('minutes_on_porch', 0))} "
                    f"min (est. {d.get('estimated_internal_c', '?')}°C in the box). It may not be safe "
                    f"to use. I've drafted a replacement request for the pharmacy with the camera evidence.")
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


    @staticmethod
    def _spanish(purpose: str, patient: str, d: dict, cold: bool) -> str | None:
        amb = d.get("ambient_c", 0)
        if purpose == "porch_patient":
            clima = "está helando" if cold else "hace mucho calor"
            return (f"Hola {patient}, le dejaron su medicina en la puerta y afuera {clima} "
                    f"({amb:.0f}°C). Por favor métala a la casa y guárdela en el refrigerador.")
        if purpose == "porch_compromised":
            return (f"{patient}, su medicina estuvo afuera unos {int(d.get('minutes_on_porch', 0))} min "
                    f"y puede que ya no sirva. No la use todavía: ya pedimos a la farmacia que la reponga.")
        if purpose == "porch_retrieved":
            return f"Listo, {patient}: su medicina ya está adentro. Guárdela en el refrigerador."
        return None


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
    def __init__(self, household: Household, notifier: Notifier, writer: Writer | None = None):
        self.household = household
        self.notifier = notifier
        self.writer = writer or TemplateWriter()
        self.incidents: dict[str, Incident] = {}

    # -- guardrails ----------------------------------------------------------------

    def allowed(self, incident: Incident, person: Person, now: datetime) -> bool:
        if incident.closed or incident.messages >= MAX_MESSAGES_PER_INCIDENT:
            return False
        return person in self.household.people

    def _send(self, kind: str, person: Person, finding: Finding, purpose: str,
              incident: Incident | None, now: datetime) -> Action | None:
        if incident is not None and not self.allowed(incident, person, now):
            return None
        message = self.writer.write(finding, person, self.household, purpose)
        delivered = self.notifier.send(person, message)
        if incident is not None:
            incident.messages += 1
            incident.last_at = now
        return Action(kind=kind, target=person.name, message=message, at=now,
                      finding_id=finding.id, delivered=delivered,
                      data={"channel": getattr(self.notifier, "channel", "app"),
                            "purpose": purpose, "role": person.role,
                            "language": person.language,
                            "writer": getattr(self.writer, "last_model", "template")})

    # -- entry points --------------------------------------------------------------

    def handle(self, finding: Finding, now: datetime) -> list[Action]:
        k = finding.kind
        exp = finding.expectation_id or finding.id
        out: list[Action | None] = []
        ladder = self.household.escalation_ladder()
        family = self.household.by_role("family")
        agency = self.household.by_role("agency")

        if k == FindingKind.PACKAGE_EXPOSED:
            # Medication just landed on a warm porch: a gentle nudge to the patient first.
            amb = finding.data.get("ambient_c", 20)
            if (amb >= HOT_PORCH_C or amb <= COLD_PORCH_C) and ladder:
                inc = self.incidents.setdefault(exp, Incident(exp, "porch", now))
                inc.finding_ids.append(finding.id)
                if inc.rung == 0:
                    inc.rung = 1
                    out.append(self._send("notify", ladder[0], finding, "porch_patient", inc, now))
        elif k == FindingKind.PACKAGE_AT_RISK:
            # Still outside and getting close to unsafe: climb one rung right away.
            inc = self.incidents.setdefault(exp, Incident(exp, "porch", now))
            inc.finding_ids.append(finding.id)
            if inc.rung == 0 and ladder:
                inc.rung = 1
                out.append(self._send("notify", ladder[0], finding, "porch_patient", inc, now))
            elif inc.rung < len(ladder):
                person = ladder[inc.rung]
                inc.rung += 1
                purpose = "porch_family" if person.role == "family" else "porch_helper"
                out.append(self._send("notify", person, finding, purpose, inc, now))
        elif k == FindingKind.PACKAGE_COMPROMISED:
            inc = self.incidents.setdefault(exp, Incident(exp, "porch", now))
            for person in [*family, ladder[0]] if ladder else family:
                out.append(self._send("notify", person, finding, "porch_compromised", inc, now))
            out.append(Action(kind="pharmacy_claim", target="Pharmacy", at=now, finding_id=finding.id,
                              message="Replacement request drafted with exposure log and camera evidence.",
                              delivered=False, data={"draft": True, **finding.data}))
        elif k == FindingKind.PACKAGE_RETRIEVED:
            inc = self.incidents.get(exp)
            if inc and not inc.closed:
                inc.closed = True
                for person in family:
                    out.append(self._send("notify", person, finding, "porch_retrieved", None, now))
        elif k == FindingKind.MISSED_VISIT:
            inc = self.incidents.setdefault(exp, Incident(exp, "visit", now))
            for person in agency:
                out.append(self._send("request_backup", person, finding, "visit_backup", inc, now))
            for person in family:
                out.append(self._send("notify", person, finding, "visit_family", inc, now))
        elif k == FindingKind.LATE_ARRIVAL and finding.severity != "info":
            inc = self.incidents.setdefault(exp, Incident(exp, "visit", now))
            for person in agency:
                out.append(self._send("notify", person, finding, "visit_agency_late", inc, now))
        elif k == FindingKind.SHORT_VISIT:
            for person in [*family, *agency]:
                out.append(self._send("notify", person, finding, "visit_short", None, now))
        return [a for a in out if a is not None]

    def followup(self, porch_findings: dict[str, Finding], now: datetime) -> list[Action]:
        """Climb the ladder for open porch incidents that nobody has resolved yet."""
        out: list[Action] = []
        ladder = self.household.escalation_ladder()
        for exp_id, finding in porch_findings.items():
            inc = self.incidents.get(exp_id)
            if not inc or inc.closed or inc.theme != "porch" or inc.last_at is None:
                continue
            if inc.rung >= len(ladder) or now - inc.last_at < LADDER_GAP:
                continue
            person = ladder[inc.rung]
            inc.rung += 1
            purpose = "porch_family" if person.role == "family" else "porch_helper"
            action = self._send("notify", person, finding, purpose, inc, now)
            if action:
                out.append(action)
        return out
