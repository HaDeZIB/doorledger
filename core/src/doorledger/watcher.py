"""Watcher: Ring frames -> perception -> Observations -> Engine.

Expectation-guided sensing: the watcher does not stare at the door all day. It opens a Ring
live view (WHEP) only while care is expected (or when a motion webhook arrives), samples
~1 frame/s for the vision model, reads presence codes on every other frame, and lets the
k-of-n porch tracker decide when something actually changed.

The same pipeline runs on recorded Ring Playground streams (``ReplaySource``), so the demo
uses real Ring footage end to end even when no live token is available.
"""

from __future__ import annotations

import asyncio
import glob
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import AsyncIterator, Callable

import cv2
import numpy as np

from . import presence
from .domain import Observation, ObservationKind, Source, new_id
from .engine import Engine
from .porch import PorchTracker
from .presence_reader import PresenceReader
from .vision import VisionClassifier

log = logging.getLogger("doorledger.watcher")


@dataclass
class Frame:
    at: datetime
    image: np.ndarray  # BGR
    source: Source


class ReplaySource:
    """Yields frames captured earlier from a Ring live view, stamped with (simulated) times."""

    def __init__(self, frames_dir: str | Path, start: datetime, *, fps: float = 1.0,
                 capture_fps: float = 4.0, limit: int | None = None,
                 source: Source = Source.RING_LIVE, realtime: float = 0.0) -> None:
        files = sorted(glob.glob(str(Path(frames_dir) / "*.jpg")))
        step = max(int(round(capture_fps / fps)), 1)
        self.files = files[::step][:limit]
        self.start, self.fps, self.source, self.realtime = start, fps, source, realtime

    async def frames(self) -> AsyncIterator[Frame]:
        for i, f in enumerate(self.files):
            img = cv2.imread(f)
            if img is None:
                continue
            yield Frame(self.start + timedelta(seconds=i / self.fps), img, self.source)
            if self.realtime:
                await asyncio.sleep(self.realtime / self.fps)


class RingLiveSource:
    """Live frames from a Ring device over WHEP (one session; caller loops for longer watches)."""

    def __init__(self, ring, device_id: str, clock: Callable[[], datetime], *, fps: float = 1.0,
                 max_seconds: float = 25.0) -> None:
        self.ring, self.device_id, self.clock = ring, device_id, clock
        self.fps, self.max_seconds = fps, max_seconds

    async def frames(self) -> AsyncIterator[Frame]:
        from ringpartner.whep import WhepSession

        async with WhepSession(self.ring, self.device_id, max_seconds=self.max_seconds) as live:
            async for vf in live.frames(fps=self.fps):
                yield Frame(self.clock(), vf.to_ndarray(format="bgr24"), Source.RING_LIVE)


class Watcher:
    def __init__(self, engine: Engine, vision: VisionClassifier, evidence_root: str | Path, *,
                 subdir: str = "captured", reader: PresenceReader | None = None,
                 presence_every: int = 2, jpeg_quality: int = 85) -> None:
        self.engine = engine
        self.vision = vision
        self.reader = reader or PresenceReader()
        self.subdir = subdir
        self.evidence_dir = Path(evidence_root) / subdir
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.presence_every = presence_every
        self.jpeg_quality = jpeg_quality
        self.used_codes: set = set()
        self.trackers: dict[str, PorchTracker] = {}
        self.frames_seen = 0
        self.last_label = None

    def tracker(self, source: Source) -> PorchTracker:
        key = str(source)
        if key not in self.trackers:
            self.trackers[key] = PorchTracker(self.engine.device.get("id"), source)
        return self.trackers[key]

    def _save(self, frame: Frame) -> tuple[str, bytes]:
        ok, buf = cv2.imencode(".jpg", frame.image, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
        data = buf.tobytes() if ok else b""
        name = f"{frame.at.strftime('%Y%m%dT%H%M%S')}_{new_id('f')}.jpg"
        (self.evidence_dir / name).write_bytes(data)
        return f"evidence/{self.subdir}/{name}", data

    def _presence(self, frame: Frame, evidence: str) -> list[Observation]:
        secrets = self.engine.visit_secrets
        if not secrets:
            return []
        result = self.reader.read(frame.image)
        out: list[Observation] = []
        at_epoch = frame.at.timestamp()
        for text in result.texts:
            for role, kind in (("in", ObservationKind.PRESENCE_CHECK_IN),
                               ("out", ObservationKind.PRESENCE_CHECK_OUT)):
                if text.startswith("DL1."):
                    res = presence.verify_code(text, secrets, role, at=at_epoch, used=self.used_codes)
                else:
                    res = presence.verify_compact_code(text, secrets, role, at=at_epoch,
                                                       used=self.used_codes)
                if res.valid:
                    out.append(Observation(kind, frame.at, frame.source, 1.0,
                                           device_id=self.engine.device.get("id"),
                                           visit_id=res.visit_id, evidence_path=evidence,
                                           detail={"method": "signed_code", "skew": res.skew}))
                    break
        return out

    async def process(self, frames: AsyncIterator[Frame]) -> list[Observation]:
        emitted: list[Observation] = []
        loop = asyncio.get_running_loop()
        async for frame in frames:
            self.frames_seen += 1
            evidence, jpeg = self._save(frame)
            obs: list[Observation] = []
            if self.frames_seen % self.presence_every == 0:
                obs += await loop.run_in_executor(None, self._presence, frame, evidence)
            label = await loop.run_in_executor(None, self.vision.classify, jpeg, frame.at, evidence)
            self.last_label = label
            obs += self.tracker(frame.source).push(label)
            for o in obs:
                self.engine.ingest(o)
                emitted.append(o)
        return emitted
