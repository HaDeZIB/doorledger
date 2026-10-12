"""Household configuration: who lives there, who to call, which Ring device watches the door."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .domain import Person


@dataclass
class Patient:
    name: str
    age: int
    address: str
    timezone: str


@dataclass
class Household:
    id: str
    patient: Patient
    people: list[Person]
    device_id: str | None = None
    device_name: str = "Front Door"
    lat: float = 41.8781
    lon: float = -87.6298
    porch_in_sun: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def by_role(self, role: str) -> list[Person]:
        return sorted((p for p in self.people if p.role == role), key=lambda p: p.escalation_order)

    def person(self, name: str) -> Person | None:
        return next((p for p in self.people if p.name.lower() == name.lower()), None)

    def escalation_ladder(self) -> list[Person]:
        """Patient first, then neighbors, then family, by escalation_order."""
        ladder = [p for p in self.people if p.role in ("patient", "neighbor", "family")]
        return sorted(ladder, key=lambda p: p.escalation_order)

    def to_api(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "patient": asdict(self.patient),
            "people": [{"name": p.name, "role": p.role, "escalation_order": p.escalation_order,
                        "language": p.language, "channel": p.channel} for p in self.people],
        }

    @classmethod
    def load(cls, path: str | Path) -> "Household":
        data = json.loads(Path(path).read_text())
        return cls(
            id=data["id"],
            patient=Patient(**data["patient"]),
            people=[Person(**p) for p in data["people"]],
            **{k: v for k, v in data.items() if k not in ("id", "patient", "people")},
        )


def demo_household() -> Household:
    """Fictional household used for the demo (no real personal data)."""
    return Household(
        id="hh_rosa",
        patient=Patient("Rosa Martínez", 81, "Chicago, IL", "America/Chicago"),
        people=[
            # Rosa uses no apps: she gets SMS (in Spanish). Ana has the family app.
            Person("Rosa Martínez", "patient", escalation_order=1, language="es", channel="sms"),
            Person("Luis (neighbor)", "neighbor", escalation_order=2, channel="sms"),
            Person("Ana Martínez (daughter)", "family", escalation_order=3, channel="push"),
            Person("BrightPath Home Care", "agency", escalation_order=10, channel="agency_portal"),
            Person("Maria (BrightPath)", "caregiver", escalation_order=20),  # never contacted
        ],
    )
