"""Domain model: what care was EXPECTED at the door vs. what the camera OBSERVED.

DoorLedger never reasons about raw video. Perception turns frames into ``Observation``s,
the day plan provides ``Expectation``s, and reconciliation compares the two to produce
``Finding``s that the agent acts on.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


class ExpectationKind(StrEnum):
    CAREGIVER_VISIT = "caregiver_visit"
    MEDICATION_DELIVERY = "medication_delivery"


class ObservationKind(StrEnum):
    PACKAGE_DROPPED = "package_dropped"
    PACKAGE_REMOVED = "package_removed"
    PERSON_AT_DOOR = "person_at_door"
    VEHICLE_ARRIVED = "vehicle_arrived"
    PRESENCE_CHECK_IN = "presence_check_in"
    PRESENCE_CHECK_OUT = "presence_check_out"


class Source(StrEnum):
    """Where an observation came from. Shown in the UI so judges can tell Ring from our footage."""

    RING_LIVE = "ring_live_view"
    RING_SNAPSHOT = "ring_snapshot"
    RING_WEBHOOK = "ring_webhook"
    OWN_FOOTAGE = "own_footage"
    SIMULATED = "simulated"


class FindingKind(StrEnum):
    ON_TIME = "on_time"
    LATE_ARRIVAL = "late_arrival"
    MISSED_VISIT = "missed_visit"
    SHORT_VISIT = "short_visit"
    VISIT_COMPLETED = "visit_completed"
    PACKAGE_EXPOSED = "package_exposed"        # on the porch, still within safe limits
    PACKAGE_AT_RISK = "package_at_risk"        # projected to cross the safe threshold soon
    PACKAGE_COMPROMISED = "package_compromised"  # estimated over threshold
    PACKAGE_RETRIEVED = "package_retrieved"
    DELIVERY_OVERDUE = "delivery_overdue"
    UNEXPECTED_ACTIVITY = "unexpected_activity"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class Person:
    name: str
    role: str  # patient | family | neighbor | agency | caregiver
    phone: str | None = None
    telegram_chat_id: str | None = None
    escalation_order: int = 99


@dataclass
class MedicationProfile:
    """Thermal tolerance of a shipped medication. Defaults are for refrigerated insulin."""

    name: str = "Insulin (refrigerated)"
    store_min_c: float = 2.0
    store_max_c: float = 8.0
    # Insulin tolerates room temperature (up to ~30 °C / 86 °F) for weeks; heat above that
    # degrades it. Stricter biologics also cap total minutes above store_max_c.
    excursion_max_c: float = 30.0
    freeze_c: float = 0.0  # insulin that has frozen must be discarded
    max_minutes_above_store: int | None = None


@dataclass
class Expectation:
    kind: ExpectationKind
    title: str
    window_start: datetime
    window_end: datetime
    id: str = field(default_factory=lambda: new_id("exp"))
    # caregiver visits
    caregiver: str | None = None
    agency: str | None = None
    planned_minutes: int | None = None
    visit_id: str | None = None  # links to the signed presence code
    # deliveries
    carrier: str | None = None
    tracking: str | None = None
    medication: MedicationProfile | None = None
    notes: str | None = None

    @property
    def grace(self) -> timedelta:
        return timedelta(minutes=15)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["window_start"] = self.window_start.isoformat()
        d["window_end"] = self.window_end.isoformat()
        return d


@dataclass
class Observation:
    kind: ObservationKind
    at: datetime
    source: Source
    confidence: float = 1.0
    id: str = field(default_factory=lambda: new_id("obs"))
    device_id: str | None = None
    visit_id: str | None = None
    evidence_path: str | None = None  # snapshot/frame saved as proof
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["at"] = self.at.isoformat()
        return d


@dataclass
class Finding:
    kind: FindingKind
    severity: Severity
    at: datetime
    summary: str
    expectation_id: str | None = None
    observation_ids: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: new_id("fnd"))

    @property
    def needs_action(self) -> bool:
        return self.severity in (Severity.WARNING, Severity.CRITICAL)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["at"] = self.at.isoformat()
        return d


@dataclass
class Action:
    """Something the agent did in the world (message sent, backup requested, record exported)."""

    kind: str
    target: str
    message: str
    at: datetime = field(default_factory=utcnow)
    finding_id: str | None = None
    id: str = field(default_factory=lambda: new_id("act"))
    delivered: bool = False
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["at"] = self.at.isoformat()
        return d
