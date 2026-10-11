"""Read-only household snapshot: export from the live engine, rebuild a sealed engine elsewhere.

The CareAgent deployed to AgentCore Runtime never sees the live ``Engine``. The API sends it a
snapshot (household roster without contact details, expectations, observations, ledger
records, the clock and the ambient temperature) and the runtime rebuilds an in-memory engine
from it. That engine:

* uses a notifier that refuses every send (``ReadOnlyNotifier``), so even a tool that tried to
  message someone would fail;
* has a frozen clock and a fixed ambient temperature (no network calls for weather);
* lives only for one invocation; nothing it writes reaches the real ledger.

Guardrails therefore stay in the DoorLedger API: the remote agent can read and explain, never act.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime
from typing import Any

from ..clock import SimClock
from ..domain import (
    Expectation,
    ExpectationKind,
    MedicationProfile,
    Observation,
    ObservationKind,
    Person,
    Source,
)
from ..engine import Engine
from ..household import Household, Patient
from ..ledger import Ledger
from ..responder import Responder, TemplateWriter
from ..weather import AmbientTemperature

SNAPSHOT_VERSION = 1
# Contact details never leave the API process.
_PRIVATE_PERSON_FIELDS = {"phone", "telegram_chat_id"}


class ReadOnlyNotifier:
    """Notifier for sealed engines: every send is refused loudly."""

    channel = "read-only"

    def send(self, person: Person, message: str) -> bool:  # noqa: ARG002
        raise PermissionError("this DoorLedger engine is a read-only snapshot; it cannot send "
                              "messages (guardrailed actions run only in the DoorLedger API)")


def _fields(cls: type) -> set[str]:
    return {f.name for f in dataclasses.fields(cls)}


def _pick(cls: type, data: dict[str, Any]) -> dict[str, Any]:
    """Keep only keys the dataclass knows (tolerates newer/older snapshot fields)."""
    names = _fields(cls)
    return {k: v for k, v in data.items() if k in names}


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


# -- export ------------------------------------------------------------------------------


def household_to_dict(hh: Household) -> dict[str, Any]:
    d = dataclasses.asdict(hh)
    d["people"] = [{k: v for k, v in p.items() if k not in _PRIVATE_PERSON_FIELDS}
                   for p in d["people"]]
    return d


def export_snapshot(engine: Engine, now: datetime | None = None) -> dict[str, Any]:
    """JSON-serialisable snapshot of one household at ``now`` (default: engine clock)."""
    with engine._lock:  # consistent view while the engine keeps ingesting
        now = now or engine.clock.now()
        try:
            ambient_c = float(engine.ambient(now))
        except Exception:  # noqa: BLE001 — weather is best-effort
            ambient_c = None
        return {
            "version": SNAPSHOT_VERSION,
            "household": household_to_dict(engine.household),
            "now": now.isoformat(),
            "ambient_c": ambient_c,
            "device": dict(engine.device),
            "expectations": [e.to_dict() for e in engine.expectations.values()],
            "observations": [o.to_dict() for o in engine.observations],
            "records": engine.ledger.records(),
        }


# -- import ------------------------------------------------------------------------------


def household_from_dict(d: dict[str, Any]) -> Household:
    data = _pick(Household, d)
    data["patient"] = Patient(**_pick(Patient, d["patient"]))
    data["people"] = [Person(**_pick(Person, p)) for p in d["people"]]
    return Household(**data)


def expectation_from_dict(d: dict[str, Any]) -> Expectation:
    data = _pick(Expectation, d)
    data["kind"] = ExpectationKind(d["kind"])
    data["window_start"] = _dt(d["window_start"])
    data["window_end"] = _dt(d["window_end"])
    if d.get("medication"):
        data["medication"] = MedicationProfile(**_pick(MedicationProfile, d["medication"]))
    return Expectation(**data)


def observation_from_dict(d: dict[str, Any]) -> Observation:
    data = _pick(Observation, d)
    data["kind"] = ObservationKind(d["kind"])
    data["at"] = _dt(d["at"])
    data["source"] = Source(d["source"])
    return Observation(**data)


def engine_from_snapshot(snap: dict[str, Any]) -> Engine:
    """Rebuild a sealed, in-memory engine. Raises ``ValueError`` on an unknown version."""
    if not isinstance(snap, dict) or snap.get("version") != SNAPSHOT_VERSION:
        raise ValueError(f"unsupported snapshot version: {snap.get('version') if isinstance(snap, dict) else snap!r}")
    hh = household_from_dict(snap["household"])
    now = datetime.fromisoformat(snap["now"])
    ledger = Ledger(":memory:", household=hh.id)
    for rec in snap.get("records", []):
        ledger._put(rec["kind"], rec["subtype"], rec["id"], datetime.fromisoformat(rec["at"]),
                    rec.get("ref"), rec["body"])
    ambient = AmbientTemperature(hh.lat, hh.lon,
                                 override_c=snap.get("ambient_c") if snap.get("ambient_c") is not None
                                 else 20.0)
    engine = Engine(hh, ledger, Responder(hh, ReadOnlyNotifier(), TemplateWriter()),
                    SimClock(now, speed=0.0), ambient, device=snap.get("device"))
    # Load state without re-running the rules: findings/actions come from the ledger as recorded.
    for e in snap.get("expectations", []):
        exp = expectation_from_dict(e)
        engine.expectations[exp.id] = exp
    engine.observations.extend(observation_from_dict(o) for o in snap.get("observations", []))
    return engine
