"""Turn noisy per-frame scene labels into discrete porch events.

Vision models flicker: one frame says "package", the next misses it behind a leg. The
tracker keeps a short sliding window per signal and only emits a transition when a clear
majority agrees (k-of-n), which is what keeps false alerts out of a family's phone.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .domain import Observation, ObservationKind, Source


@dataclass
class FrameLabel:
    """What a vision model reported for one frame (see vision.py for the JSON contract)."""

    at: datetime
    package_visible: bool = False
    person_present: bool = False
    person_carrying_package: bool = False
    vehicle_present: bool = False
    confidence: float = 1.0
    note: str | None = None
    evidence_path: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class _Signal:
    def __init__(self, window: int, k_on: int, k_off: int) -> None:
        self.window: deque[bool] = deque(maxlen=window)
        self.k_on = k_on
        self.k_off = k_off
        self.state = False

    def push(self, value: bool) -> bool | None:
        """Return the new state when it flips, else None."""
        self.window.append(value)
        on = sum(self.window)
        off = len(self.window) - on
        if not self.state and on >= self.k_on:
            self.state = True
            return True
        if self.state and off >= self.k_off:
            self.state = False
            return False
        return None


class PorchTracker:
    def __init__(
        self,
        device_id: str | None = None,
        source: Source = Source.RING_LIVE,
        *,
        window: int = 5,
        k_on: int = 3,
        k_off: int = 4,
        min_confidence: float = 0.5,
    ) -> None:
        self.device_id = device_id
        self.source = source
        self.min_confidence = min_confidence
        self.package = _Signal(window, k_on, k_off)
        self.person = _Signal(window, k_on, k_off)
        self.vehicle = _Signal(window, k_on, k_off)
        self._last_evidence: str | None = None

    def seed(self, *, package_present: bool = False) -> None:
        """Start from a known state (e.g. a package was already on the porch at session start)."""
        self.package.state = package_present

    def push(self, label: FrameLabel) -> list[Observation]:
        if label.confidence < self.min_confidence:
            return []
        if label.evidence_path:
            self._last_evidence = label.evidence_path
        out: list[Observation] = []

        def obs(kind: ObservationKind, **detail: Any) -> Observation:
            return Observation(
                kind=kind,
                at=label.at,
                source=self.source,
                confidence=label.confidence,
                device_id=self.device_id,
                evidence_path=label.evidence_path or self._last_evidence,
                detail={k: v for k, v in detail.items() if v is not None},
            )

        flip = self.person.push(label.person_present)
        if flip is True:
            out.append(obs(ObservationKind.PERSON_AT_DOOR, carrying_package=label.person_carrying_package,
                           note=label.note))

        flip = self.vehicle.push(label.vehicle_present)
        if flip is True:
            out.append(obs(ObservationKind.VEHICLE_ARRIVED, note=label.note))

        flip = self.package.push(label.package_visible)
        if flip is True:
            out.append(obs(ObservationKind.PACKAGE_DROPPED, note=label.note))
        elif flip is False:
            out.append(obs(ObservationKind.PACKAGE_REMOVED, note=label.note))
        return out
