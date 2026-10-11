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
from dataclasses import dataclass, replace
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
    # Wall-clock capture time, used to verify time-based presence codes. Differs from ``at``
    # when recorded footage is replayed inside a simulated day.
    captured_at: float | None = None


class ReplaySource:
    """Yields frames captured earlier from a Ring live view, stamped with (simulated) times."""

    def __init__(self, frames_dir: str | Path, start: datetime, *, fps: float = 1.0,
                 capture_fps: float = 4.0, limit: int | None = None,
                 source: Source = Source.RING_LIVE, realtime: float = 0.0,
                 recorded_start: float | None = None) -> None:
        files = sorted(glob.glob(str(Path(frames_dir) / "*.jpg")))
        step = max(int(round(capture_fps / fps)), 1)
        self.files = files[::step][:limit]
        self.start, self.fps, self.source, self.realtime = start, fps, source, realtime
        self.capture_fps = capture_fps
        self.step = step
        self.recorded_start = recorded_start  # epoch of the first captured frame, if known

    async def frames(self) -> AsyncIterator[Frame]:
        for i, f in enumerate(self.files):
            img = cv2.imread(f)
            if img is None:
                continue
            captured = (None if self.recorded_start is None
                        else self.recorded_start + i * self.step / self.capture_fps)
            yield Frame(self.start + timedelta(seconds=i / self.fps), img, self.source, captured)
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
                 presence_every: int = 2, jpeg_quality: int = 85, redact_faces: bool = True,
                 motion_threshold: float = 2.5, max_reuse: int = 4) -> None:
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
        # Privacy: pixelate faces in stored evidence. Cost: skip the vision call when the scene
        # hasn't changed, re-using the last label (at most `max_reuse` frames in a row).
        from .privacy import FaceRedactor

        self.redactor = FaceRedactor() if redact_faces else None
        self.faces_redacted = 0
        self.motion_threshold = motion_threshold
        self.max_reuse = max_reuse
        self._last_thumb: np.ndarray | None = None
        self._reused = 0
        self.vision_calls = 0
        self.vision_skipped = 0
        self.frames_persisted = 0

    def tracker(self, source: Source) -> PorchTracker:
        key = str(source)
        if key not in self.trackers:
            self.trackers[key] = PorchTracker(self.engine.device.get("id"), source)
        return self.trackers[key]

    def _encode(self, image: np.ndarray) -> bytes:
        ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
        return buf.tobytes() if ok else b""

    def _redacted(self, frame: Frame) -> bytes:
        """JPEG of the frame with faces pixelated. This is what Bedrock sees and what is stored."""
        image, n = self.redactor.redact(frame.image) if self.redactor else (frame.image, 0)
        self.faces_redacted += n
        return self._encode(image)

    def _persist(self, frame: Frame, jpeg: bytes) -> str:
        """Store an evidence frame — only called when an observation was confirmed."""
        name = f"{frame.at.strftime('%Y%m%dT%H%M%S')}_{new_id('f')}.jpg"
        (self.evidence_dir / name).write_bytes(jpeg)
        self.frames_persisted += 1
        return f"evidence/{self.subdir}/{name}"

    def _changed(self, image: np.ndarray) -> bool:
        """Cheap motion gate: mean absolute difference on a tiny grayscale thumbnail."""
        thumb = cv2.cvtColor(cv2.resize(image, (64, 36)), cv2.COLOR_BGR2GRAY).astype(np.int16)
        prev, self._last_thumb = self._last_thumb, thumb
        if prev is None:
            return True
        return float(np.abs(thumb - prev).mean()) >= self.motion_threshold

    def _presence(self, frame: Frame, evidence: str | None) -> list[Observation]:
        secrets = self.engine.visit_secrets
        if not secrets:
            return []
        result = self.reader.read(frame.image)
        out: list[Observation] = []
        at_epoch = frame.captured_at if frame.captured_at is not None else frame.at.timestamp()
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
                                           detail={"method": "signed_code", "skew": res.skew,
                                                   "proves": "a device showing this visit's "
                                                             "current signed code was at the door"}))
                    break
        return out

    async def process(self, frames: AsyncIterator[Frame], *,
                      presence_every: int | None = None) -> list[Observation]:
        """Run perception over frames. Privacy rules:
        * faces are pixelated BEFORE the frame is sent to Bedrock;
        * nothing is written to disk unless an observation is confirmed (then only that frame);
        * the raw frame is used in memory only by the on-device presence-code reader.
        ``presence_every=1`` is the burst mode used right after a doorbell press.
        """
        emitted: list[Observation] = []
        loop = asyncio.get_running_loop()
        every = presence_every or self.presence_every
        for_sub = 0
        async for frame in frames:
            self.frames_seen += 1
            for_sub += 1
            jpeg: bytes | None = None
            obs: list[Observation] = []
            if for_sub % every == 0:
                obs += await loop.run_in_executor(None, self._presence, frame, None)
            if (self.last_label is not None and not self._changed(frame.image)
                    and self._reused < self.max_reuse):
                self._reused += 1
                self.vision_skipped += 1
                label = replace(self.last_label, at=frame.at, evidence_path=None)
            else:
                if self.last_label is None:
                    self._changed(frame.image)  # prime the motion gate
                self._reused = 0
                self.vision_calls += 1
                jpeg = await loop.run_in_executor(None, self._redacted, frame)
                label = await loop.run_in_executor(None, self.vision.classify, jpeg, frame.at, None)
            self.last_label = label
            obs += self.tracker(frame.source).push(label)
            if obs:
                if jpeg is None:
                    jpeg = await loop.run_in_executor(None, self._redacted, frame)
                path = self._persist(frame, jpeg)
                for o in obs:
                    o.evidence_path = o.evidence_path or path
            for o in obs:
                self.engine.ingest(o)
                emitted.append(o)
        return emitted


def purge_evidence(evidence_dir: str | Path, older_than_days: float) -> int:
    """Delete stored evidence frames older than the retention window. Returns files removed."""
    import time

    cutoff = time.time() - older_than_days * 86400
    removed = 0
    for f in Path(evidence_dir).glob("*.jpg"):
        if f.stat().st_mtime < cutoff:
            f.unlink()
            removed += 1
    return removed
