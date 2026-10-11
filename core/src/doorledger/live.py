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
from datetime import timedelta
from pathlib import Path

from ringpartner.webhooks import WebhookEvent

from .engine import Engine
from .watcher import ReplaySource, RingLiveSource, Watcher

log = logging.getLogger("doorledger.live")

SCENE_FOR_SUBTYPE = {"package_delivery": "package", "vehicle": "vehicle", "human": "package",
                     "motion": "default", "other_motion": "default"}
SESSION_SECONDS = 25.0
SESSION_GAP_SECONDS = 20.0  # opening a new WHEP session sooner returns HTTP 500 (friction log F6)


class LiveController:
    def __init__(self, engine: Engine, watcher: Watcher | None, replay_root: Path) -> None:
        self.engine = engine
        self.watcher = watcher
        self.replay_root = replay_root
        self.seen_requests: set[str] = set()
        self.busy = asyncio.Lock()
        self.watch_task: asyncio.Task | None = None
        self.sessions = 0

    @property
    def token(self) -> str | None:
        return os.environ.get("RING_ACCESS_TOKEN") or None

    async def _ring(self):
        from ringpartner import AsyncRingClient

        return AsyncRingClient(self.token)

    async def watch_once(self, reason: str, scene: str = "default") -> int:
        """One watch session: live WHEP if a token is configured, else recorded footage."""
        if self.watcher is None:
            return 0
        async with self.busy:
            self.sessions += 1
            if self.token:
                ring = await self._ring()
                try:
                    device_id = self.engine.device.get("id") or (await ring.devices())[0].id
                    self.engine.device.update({"id": device_id, "online": True,
                                               "source": "ring_playground"})
                    src = RingLiveSource(ring, device_id, self.engine.clock.now,
                                         max_seconds=SESSION_SECONDS)
                    found = await self.watcher.process(src.frames())
                finally:
                    await ring.aclose()
            else:
                frames = self.replay_root / scene / "frames"
                src = ReplaySource(frames, self.engine.clock.now(), capture_fps=1.0, limit=6)
                found = await self.watcher.process(src.frames())
            log.info("watch session (%s) produced %d observations", reason, len(found))
            return len(found)

    async def on_webhook(self, event: WebhookEvent) -> str:
        if event.dedupe_key in self.seen_requests:
            return "duplicate"
        self.seen_requests.add(event.dedupe_key)
        if event.type in ("motion_detected", "button_press"):
            scene = SCENE_FOR_SUBTYPE.get(event.sub_type or "", "default")
            if event.type == "button_press":
                scene = "package"
            asyncio.create_task(self.watch_once(f"webhook:{event.type}:{event.sub_type}", scene))
            return "watching"
        if event.type in ("device_online", "device_offline"):
            self.engine.device["online"] = event.type == "device_online"
        return "recorded"

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

    def start_watching(self) -> bool:
        if self.watch_task and not self.watch_task.done():
            return False
        self.watch_task = asyncio.create_task(self._watch_loop())
        return True

    def stop_watching(self) -> None:
        if self.watch_task:
            self.watch_task.cancel()
            self.watch_task = None
