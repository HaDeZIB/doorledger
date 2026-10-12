"""Event-driven and expectation-guided watching of a real Ring device.

Two triggers open a Ring live view (WHEP) and run the watcher:

1. **Ring webhooks** (``motion_detected``, ``button_press``): verified with the partner HMAC
   key, de-duplicated on ``request_id``, answered within Ring's 5 s budget, then a short watch
   session runs in the background.
2. **Care windows**: while a visit or delivery is expected, the controller re-opens a session
   periodically (Ring caps sessions at 30–60 s).

Without a live token the same code paths run on recorded Ring Playground footage, chosen by
the webhook's ``sub_type`` — so the event-driven flow is demonstrable end to end even though
the Playground itself never sends webhooks.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ringpartner.webhooks import WebhookEvent

from .engine import Engine
from .watcher import ReplaySource, RingLiveSource, Watcher

log = logging.getLogger("doorledger.live")

SCENE_FOR_SUBTYPE = {"package_delivery": "package", "vehicle": "vehicle", "human": "package",
                     "motion": "default", "other_motion": "default"}
SESSION_SECONDS = 25.0
SESSION_GAP_SECONDS = 20.0  # opening a new WHEP session sooner returns HTTP 500 (friction log F6)

# Ring history rows the poller acts on (``event_types`` filter, OR-combined): a doorbell press
# (burst mode for the aide's code), live views (the Playground's Package/Vehicle/Motion buttons
# create ``on_demand`` rows, friction log F3), and Smart Alerts motion for people and vehicles.
# Animals and unclassified motion never open a session. Devices without Smart Alerts report
# plain ``motion``: set DOORLEDGER_RING_EVENT_TYPES=ding,on_demand,motion for those.
HISTORY_EVENT_TYPES = ("ding", "on_demand", "motion.human", "motion.vehicle")
# Our own WHEP sessions also show up as ``on_demand`` rows; never react to those.
OWN_SESSION_SLACK = timedelta(seconds=10)


def history_event_types() -> list[str]:
    env = os.environ.get("DOORLEDGER_RING_EVENT_TYPES", "")
    types = [t.strip() for t in env.split(",") if t.strip()]
    return types or list(HISTORY_EVENT_TYPES)


class LiveController:
    def __init__(self, engine: Engine, watcher: Watcher | None, replay_root: Path) -> None:
        self.engine = engine
        self.watcher = watcher
        self.replay_root = replay_root
        self.seen_requests: set[str] = set()
        self.seen_events: set[str] = set()
        self.ring_events: list[dict] = []
        self.own_sessions: deque[tuple[datetime, datetime]] = deque(maxlen=50)  # wall clock, UTC
        self.last_snapshot: bytes | None = None
        self.busy = asyncio.Lock()
        self.watch_task: asyncio.Task | None = None
        self.sessions = 0

    @property
    def token(self) -> str | None:
        return os.environ.get("RING_ACCESS_TOKEN") or None

    async def _ring(self):
        from ringpartner import AsyncRingClient

        return AsyncRingClient(self.token)

    async def _prepare_device(self, ring) -> str | None:
        """Discover the device and load what governs what we may look at: privacy zones (never
        analyzed or stored) and end-to-end encryption (E2EE/TAKE video is unreadable — skip)."""
        from .privacy import privacy_zones_from_configurations

        devices = await ring.devices()
        device = next((d for d in devices if d.id == self.engine.device.get("id")), None) or (
            devices[0] if devices else None)
        if device is None:
            return None
        self.engine.device.update({
            "id": device.id, "name": device.name, "online": device.online,
            "source": "ring_playground",
            "privacy_zones": privacy_zones_from_configurations(device.configurations),
            "encrypted": bool(device.is_encrypted),
        })
        if device.is_encrypted:
            log.warning("device %s has end-to-end encryption on; video analysis disabled", device.id)
            return None
        return device.id

    async def watch_once(self, reason: str, scene: str = "default", *, burst: bool = False) -> int:
        """One watch session: live WHEP if a token is configured, else recorded footage.

        ``burst`` (after a doorbell press): 4 fps for ~12 s and the presence-code reader runs on
        every frame, so an aide holding her pass for 2–3 s gets ~10 read attempts.
        """
        if self.watcher is None:
            return 0
        async with self.busy:
            self.sessions += 1
            if self.token:
                ring = await self._ring()
                try:
                    device_id = await self._prepare_device(ring)
                    if device_id is None:
                        return 0
                    src = RingLiveSource(ring, device_id, self.engine.clock.now,
                                         fps=4.0 if burst else 1.0,
                                         max_seconds=12.0 if burst else SESSION_SECONDS)
                    opened = datetime.now(timezone.utc)
                    try:
                        found = await self.watcher.process(src.frames(),
                                                           presence_every=1 if burst else None)
                    finally:
                        self.own_sessions.append((opened, datetime.now(timezone.utc)))
                finally:
                    await ring.aclose()
            else:
                frames = self.replay_root / scene / "frames"
                src = ReplaySource(frames, self.engine.clock.now(), capture_fps=1.0, limit=6)
                found = await self.watcher.process(src.frames(),
                                                   presence_every=1 if burst else None)
            log.info("watch session (%s) produced %d observations", reason, len(found))
            return len(found)

    async def on_webhook(self, event: WebhookEvent) -> str:
        if event.dedupe_key in self.seen_requests:
            return "duplicate"
        self.seen_requests.add(event.dedupe_key)
        if event.type in ("motion_detected", "button_press"):
            scene = SCENE_FOR_SUBTYPE.get(event.sub_type or "", "default")
            burst = event.type == "button_press"  # "ring the bell, then show your pass"
            if burst:
                scene = "package"
            asyncio.create_task(self.watch_once(f"webhook:{event.type}:{event.sub_type}", scene,
                                                burst=burst))
            return "watching"
        if event.type in ("device_online", "device_offline"):
            self.engine.device["online"] = event.type == "device_online"
        return "recorded"

    def _is_own_session(self, event) -> bool:
        """An ``on_demand`` row that Ring logged for one of OUR live-view sessions."""
        if event.event_type != "on_demand" or event.start is None:
            return False
        return any(a - OWN_SESSION_SLACK <= event.start <= b + OWN_SESSION_SLACK
                   for a, b in self.own_sessions)

    def record_ring_event(self, event, *, action: str) -> dict:
        """Put a Ring history row on the ledger (kind ``ring_event``), so the dashboard timeline
        and the ledger show what Ring itself recorded, labelled with that source."""
        body = {"id": event.id, "event_type": event.event_type,
                "at": event.start.isoformat() if event.start else None,
                "end": event.end.isoformat() if event.end else None,
                "device_id": event.device_id or self.engine.device.get("id"),
                "source": "ring_history", "action": action}
        self.ring_events.append({"id": event.id, "type": event.event_type, "at": body["at"]})
        self.engine.ledger.add_ring_event(body, event.start or self.engine.clock.now())
        return body

    def windows_open(self) -> bool:
        now = self.engine.clock.now()
        pad = timedelta(minutes=30)
        return any(e.window_start - pad <= now <= e.window_end + pad
                   for e in self.engine.expectations.values())

    async def _watch_loop(self) -> None:
        while self.windows_open():
            try:
                await self.watch_once("care_window")
            except Exception as exc:  # noqa: BLE001 — keep watching through transient errors
                log.warning("watch session failed: %s", exc)
            await asyncio.sleep(SESSION_GAP_SECONDS)

    async def _poll_history_loop(self, interval: float = 15.0) -> None:
        """Battery-friendly default: poll Ring event history and open live view only when Ring
        itself recorded something new (motion, ding, or a Playground live-view event).

        Every new event also fetches a Ring snapshot at the event's start time
        (``POST /media/image/download`` with ``at_timestamp`` — the range form returns 403).
        Only ``history_event_types()`` are requested, and each one acted on is written to the
        ledger as a ``ring_event`` record.
        """
        started = datetime.now(timezone.utc)
        ring = await self._ring()
        try:
            device_id = await self._prepare_device(ring)
            if device_id is None:
                return
            types = history_event_types()
            while self.windows_open():
                try:
                    page = await ring.history(device_id, event_types=types)
                    new = [e for e in page.events
                           if e.id not in self.seen_events and e.start and e.start >= started]
                    for e in sorted(new, key=lambda e: e.start):
                        self.seen_events.add(e.id)
                        if self._is_own_session(e):
                            continue
                        burst = e.event_type == "ding"
                        self.record_ring_event(e, action="burst watch" if burst else "watch")
                        try:
                            snap = await ring.snapshot(device_id, at=e.start)
                            self.last_snapshot = snap.content
                            await self._classify_snapshot(snap.content, e.start)
                        except Exception as exc:  # noqa: BLE001 — snapshots are best-effort
                            log.info("snapshot unavailable for %s: %s", e.id, exc)
                        await self.watch_once(f"ring_history:{e.event_type}", burst=burst)
                except Exception as exc:  # noqa: BLE001
                    log.warning("history poll failed: %s", exc)
                await asyncio.sleep(interval)
        finally:
            await ring.aclose()

    async def _classify_snapshot(self, jpeg: bytes, at) -> None:
        """Run the Ring snapshot taken at the event's start through the same perception path."""
        import cv2
        import numpy as np

        from .domain import Source
        from .watcher import Frame

        if self.watcher is None or not jpeg:
            return
        image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            return

        async def one():
            yield Frame(self.engine.clock.now(), image, Source.RING_SNAPSHOT, at.timestamp())

        await self.watcher.process(one())

    def start_watching(self) -> bool:
        """With a live token: poll Ring history (event-driven). Without: periodic replay sessions."""
        if self.watch_task and not self.watch_task.done():
            return False
        loop = self._poll_history_loop() if self.token else self._watch_loop()
        self.watch_task = asyncio.create_task(loop)
        return True

    def stop_watching(self) -> None:
        if self.watch_task:
            self.watch_task.cancel()
            self.watch_task = None
