"""Live end-to-end run: a Ring event becomes Rosa's phone call, with every step timed.

The video's one unbroken take (docs/LIVE_DEMO.md):

    click "Package" in the Ring Developer Playground
      -> Ring logs an ``on_demand`` history row          (Ring clock: the moment of the click)
      -> the history poller notices the new row          (``live.LiveController``)
      -> Ring snapshots at the row's start               (``at_timestamp``; range form is 403)
      -> privacy zones blacked out, faces pixelated      (``watcher.Watcher``)
      -> Amazon Nova 2 Lite on Bedrock labels the frame  (``vision.BedrockVision``)
      -> porch tracker k-of-n vote: package dropped      (``porch.PorchTracker``)
      -> reconcile: insulin on a freezing porch          (``reconcile``, deterministic)
      -> responder: Rosa's Spanish call + SMS            (Amazon Connect + Amazon SNS)

``LiveTrace`` records each step with wall-clock time and measured latency; the API serves it
at ``/api/live/trace`` and the dashboard shows it.

**Safety.** A live run places at most ``max_calls`` calls (default 1) and ``max_sms`` SMS
(default 1). Only the patient is ever called, only ``DOORLEDGER_VOICE_TO`` is ever dialled, and
SMS go only to ``DOORLEDGER_SMS_TO`` (any per-person number is dropped). The +5 min re-call and
the neighbor/family rungs are skipped unless ``full_ladder`` is set. Under pytest the wrappers
refuse to build a real Amazon Connect or SNS client.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .clock import WallClock
from .domain import Expectation, ExpectationKind, MedicationProfile, Person
from .engine import Engine
from .notify import ConnectVoiceNotifier, FanOutNotifier, SNSNotifier
from .porch import FrameLabel
from .responder import Responder

log = logging.getLogger("doorledger.live_session")

ROOT = Path(__file__).resolve().parents[3]
# Gitignored (fixtures/raw/): traces, the live vision cache and probe captures stay local.
RUNS_DIR = ROOT / "fixtures" / "raw" / "live_runs"
TRIGGERS = ("history", "whep", "both")
MAX_STEPS = 400
MAX_VISION_STEPS = 40  # a long WHEP watch would otherwise flood the trace; counts keep going

STEP_LABELS = {
    "armed": "Live run armed: watching the Ring device",
    "ring_event": "Ring event (history row)",
    "frame": "Frame from Ring",
    "vision": "Amazon Nova 2 Lite labelled the frame",
    "porch": "Porch tracker decision (k-of-n)",
    "finding": "Reconciliation finding",
    "call": "Call to Rosa (Amazon Connect)",
    "sms": "SMS to Rosa (Amazon SNS)",
    "call_outcome": "Call outcome",
    "cancelled": "Step cancelled",
    "skipped": "Skipped by the live-run safety cap",
    "suppressed": "Blocked by the live-run safety cap",
    "error": "Problem",
    "stopped": "Live run stopped",
}


class ZonedWallClock(WallClock):
    """Real time in the household's time zone, so finding texts ("delivered at 14:07") read in
    Rosa's local time like the rest of the dashboard."""

    def __init__(self, tz: str) -> None:
        from zoneinfo import ZoneInfo

        self.tz = ZoneInfo(tz)

    def now(self) -> datetime:
        return datetime.now(self.tz)


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _ms(a: datetime | None, b: datetime | None) -> int | None:
    if a is None or b is None:
        return None
    return round((b - a).total_seconds() * 1000)


@dataclass
class LiveOptions:
    trigger: str = "history"  # history | whep | both
    max_calls: int = 1
    max_sms: int = 1
    full_ladder: bool = False
    dry_run: bool = False  # Ring + Bedrock live, but no call and no SMS leave the machine
    ambient_c: float | None = -9.0  # the Chicago-winter story; None = Open-Meteo
    minutes: float = 10.0
    poll_s: float = 2.0
    snapshots: int = 3
    whep_followup: bool = False
    device_id: str | None = None
    rehearsal: bool = False  # offline: recorded Playground data, recorded Bedrock labels

    def __post_init__(self) -> None:
        if self.trigger not in TRIGGERS:
            raise ValueError(f"trigger must be one of {TRIGGERS}")
        if self.max_calls < 0 or self.max_sms < 0:
            raise ValueError("caps must be >= 0")


# ---------------------------------------------------------------------------------------
# trace
# ---------------------------------------------------------------------------------------


class LiveTrace:
    """Timestamped steps of one live run. Thread-safe: vision runs in executor threads and a
    call's outcome arrives on a polling thread."""

    def __init__(self, opts: LiveOptions, *, run_id: str | None = None,
                 out_dir: Path | None = RUNS_DIR) -> None:
        self.opts = opts
        self.run_id = run_id or f"live_{_now().strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:4]}"
        self.out_dir = out_dir
        self.started_at = _now()
        self.ends_at: datetime | None = None
        self.stopped_at: datetime | None = None
        self.steps: list[dict[str, Any]] = []
        self.device: dict[str, Any] = {}
        self.counts = {"ring_events": 0, "frames": 0, "vision_calls": 0, "calls_placed": 0,
                       "sms_sent": 0, "suppressed": 0}
        self._vision_steps = 0
        self._skipped: set[str] = set()
        self._lock = threading.Lock()

    @property
    def active(self) -> bool:
        return self.stopped_at is None

    def mark(self, step: str, *, at: datetime | None = None, **detail: Any) -> dict[str, Any] | None:
        with self._lock:
            if step == "vision":
                self.counts["vision_calls"] += 1
                self._vision_steps += 1
                if self._vision_steps > MAX_VISION_STEPS:
                    return None
            if step == "frame":
                self.counts["frames"] += detail.get("count", 1)
            if step == "ring_event":
                self.counts["ring_events"] += 1
            if step == "suppressed":
                self.counts["suppressed"] += 1
            if step == "skipped":
                key = str(detail.get("what"))
                if key in self._skipped:
                    return None
                self._skipped.add(key)
            if len(self.steps) >= MAX_STEPS:
                return None
            entry = {"step": step, "label": STEP_LABELS.get(step, step),
                     "at": (at or _now()).isoformat(),
                     "detail": {k: v for k, v in detail.items() if v is not None}}
            self.steps.append(entry)
        log.info("[live] %s %s", step, entry["detail"])
        return entry

    # -- ledger listener: everything the engine records ----------------------------------

    def on_record(self, record: dict[str, Any]) -> None:
        kind, sub, body = record.get("kind"), record.get("subtype"), record.get("body") or {}
        if kind == "ring_event":
            self.mark("ring_event", ring_at=body.get("at"), event_type=body.get("event_type"),
                      event_id=str(body.get("id", ""))[-8:], action=body.get("action"))
        elif kind == "observation":
            detail = body.get("detail") or {}
            self.mark("porch", observation=str(sub), source=str(body.get("source")),
                      confidence=body.get("confidence"), rule="3 of the last 5 frames agree",
                      vision_model=detail.get("vision_model"), vision_ms=detail.get("vision_ms"),
                      vision_reused=detail.get("vision_reused"), note=detail.get("note"),
                      evidence=body.get("evidence_path"))
        elif kind == "finding":
            data = body.get("data") or {}
            self.mark("finding", finding=str(sub), severity=str(body.get("severity")),
                      summary=body.get("summary"), ambient_c=data.get("ambient_c"),
                      direction=data.get("direction"))
        elif kind == "action":
            data = body.get("data") or {}
            if sub == "cancelled":
                self.mark("cancelled", message=body.get("message"))
            elif data.get("channel") == "voice":
                status = data.get("status")
                if status in ("answered", "no_answer"):
                    with self._lock:
                        done = any(s["step"] == "call_outcome" for s in self.steps)
                    if not done:
                        self.mark("call_outcome", status=status, target=body.get("target"))
                elif status == "not_placed":
                    self.mark("call", status="not placed (dry run / Connect not configured)",
                              target=body.get("target"), script=body.get("message"))

    # -- summary -------------------------------------------------------------------------

    def latency(self) -> dict[str, Any]:
        with self._lock:
            steps = list(self.steps)

        def first(step, pred=lambda s: True):
            return next((s for s in steps if s["step"] == step and pred(s)), None)

        def at(s):
            return datetime.fromisoformat(s["at"]) if s else None

        ev = first("ring_event")
        ring_at = datetime.fromisoformat(ev["detail"]["ring_at"]) if ev and ev["detail"].get(
            "ring_at") else None
        frame = first("frame")
        vision = first("vision", lambda s: s["detail"].get("package_visible")) or first("vision")
        porch = first("porch", lambda s: s["detail"].get("observation") == "package_dropped")
        call = first("call", lambda s: s["detail"].get("status") == "placed")
        sms = first("sms", lambda s: s["detail"].get("delivered"))
        answered = first("call_outcome", lambda s: s["detail"].get("status") == "answered")
        base = ring_at or self.started_at
        return {
            "base": "ring_event" if ring_at else "armed",
            "ring_event_at": _iso(ring_at),
            "ring_event_to_noticed_ms": _ms(ring_at, at(ev)),
            "snapshot_ms": frame["detail"].get("ms") if frame else None,
            "vision_ms": vision["detail"].get("ms") if vision else None,
            "frame_to_decision_ms": _ms(at(frame), at(porch)),
            "decision_to_call_ms": _ms(at(porch), at(call)),
            "ring_event_to_decision_ms": _ms(base, at(porch)),
            "ring_event_to_call_ms": _ms(base, at(call)),
            "ring_event_to_sms_ms": _ms(base, at(sms)),
            "call_to_answer_ms": _ms(at(call), at(answered)),
        }

    def to_api(self) -> dict[str, Any]:
        lat = self.latency()
        base = (datetime.fromisoformat(lat["ring_event_at"]) if lat["ring_event_at"]
                else self.started_at)
        with self._lock:
            steps = [{**s, "t_ms": _ms(base, datetime.fromisoformat(s["at"]))}
                     for s in self.steps]
            counts = dict(self.counts)
        o = self.opts
        return {
            "run_id": self.run_id,
            "active": self.active,
            "source": "rehearsal" if o.rehearsal else "live",
            "replay": o.rehearsal,
            "dry_run": o.dry_run or o.rehearsal,
            "trigger": o.trigger,
            "device": self.device,
            "started_at": _iso(self.started_at),
            "ends_at": _iso(self.ends_at),
            "stopped_at": _iso(self.stopped_at),
            "caps": {"max_calls": o.max_calls, "max_sms": o.max_sms,
                     "full_ladder": o.full_ladder},
            "ambient": {"celsius": o.ambient_c,
                        "source": "set for the story" if o.ambient_c is not None else "open-meteo"},
            "steps": steps,
            "latency": lat,
            "counts": counts,
        }

    def save(self) -> Path | None:
        if self.out_dir is None:
            return None
        self.out_dir.mkdir(parents=True, exist_ok=True)
        path = self.out_dir / f"{self.run_id}.json"
        path.write_text(json.dumps(self.to_api(), indent=1))
        return path


# ---------------------------------------------------------------------------------------
# safety caps around the real channels
# ---------------------------------------------------------------------------------------


def _real_aws_client_pending(obj: Any) -> bool:
    """True when ``obj`` would build a real boto3 client (Connect or SNS) on first use."""
    if isinstance(obj, FanOutNotifier):
        return any(_real_aws_client_pending(n) for n in obj.notifiers)
    return isinstance(obj, (ConnectVoiceNotifier, SNSNotifier)) and obj._client is None


def _refuse_under_pytest(obj: Any, what: str) -> None:
    if os.environ.get("PYTEST_CURRENT_TEST") and _real_aws_client_pending(obj):
        raise RuntimeError(f"refusing a real {what} under pytest")


class CappedVoice:
    """At most ``max_calls`` call attempts per run, only to the patient, only to
    ``DOORLEDGER_VOICE_TO`` (the one verified test phone)."""

    channel = "voice"

    def __init__(self, inner: Any, max_calls: int = 1, trace: LiveTrace | None = None) -> None:
        to = getattr(inner, "to", None)
        if to is not None and to != os.environ.get("DOORLEDGER_VOICE_TO", ""):
            raise ValueError("live calls may only dial DOORLEDGER_VOICE_TO")
        self.inner, self.max_calls, self.trace = inner, max_calls, trace
        self.attempts = 0
        self.suppressed = 0

    def _mark(self, step: str, **detail: Any) -> None:
        if self.trace is not None:
            self.trace.mark(step, **detail)

    def call(self, person: Person, ssml: str) -> str | None:
        _refuse_under_pytest(self.inner, "Amazon Connect call")
        if person.role != "patient" or self.attempts >= self.max_calls:
            self.suppressed += 1
            self._mark("suppressed", what="call", target=person.name,
                       reason=f"live run allows {self.max_calls} call(s), to the patient only")
            return None
        self.attempts += 1
        t0 = time.perf_counter()
        contact_id = self.inner.call(person, ssml)
        ms = round((time.perf_counter() - t0) * 1000)
        if contact_id:
            if self.trace is not None:
                self.trace.counts["calls_placed"] += 1
            self._mark("call", status="placed", target=person.name, connect_ms=ms,
                       contact=f"…{str(contact_id)[-6:]}", api="StartOutboundVoiceContact")
        else:
            self._mark("call", status="failed", target=person.name, connect_ms=ms)
        return contact_id

    def watch(self, contact_id: str, on_status) -> None:
        self.inner.watch(contact_id, on_status)

    def status(self, contact_id: str) -> str | None:
        return self.inner.status(contact_id)


class CappedNotifier:
    """At most ``max_sms`` texts per run, always to the configured demo destination."""

    def __init__(self, inner: Any, max_sms: int = 1, trace: LiveTrace | None = None) -> None:
        self.inner, self.max_sms, self.trace = inner, max_sms, trace
        self.channel = getattr(inner, "channel", "app")
        self.sent = 0
        self.suppressed = 0

    def _mark(self, step: str, **detail: Any) -> None:
        if self.trace is not None:
            self.trace.mark(step, **detail)

    def send(self, person: Person, message: str) -> bool:
        _refuse_under_pytest(self.inner, "Amazon SNS SMS")
        if self.sent >= self.max_sms:
            self.suppressed += 1
            self._mark("suppressed", what="sms", target=person.name,
                       reason=f"live run allows {self.max_sms} SMS")
            return False
        self.sent += 1
        # Never a household member's own number: only DOORLEDGER_SMS_TO / the demo chat.
        safe = replace(person, phone=None, telegram_chat_id=None)
        t0 = time.perf_counter()
        ok = bool(self.inner.send(safe, message))
        ms = round((time.perf_counter() - t0) * 1000)
        if ok and self.channel != "app" and self.trace is not None:
            self.trace.counts["sms_sent"] += 1
        self._mark("sms", delivered=ok and self.channel != "app", via=self.channel,
                   target=person.name, api_ms=ms,
                   note=None if self.channel != "app" else "dry run: console only, not sent")
        return ok


class TracedVision:
    """Times every vision call and puts it on the trace (model, latency, what it saw)."""

    def __init__(self, inner: Any, trace: LiveTrace, watcher: Any = None) -> None:
        self.inner, self.trace, self.watcher = inner, trace, watcher
        nested = getattr(inner, "inner", None)
        self.model_id = getattr(inner, "model_id", None) or getattr(nested, "model_id", None)

    def classify(self, image_jpeg: bytes, at: datetime,
                 evidence_path: str | None = None) -> FrameLabel:
        t0 = time.perf_counter()
        label = self.inner.classify(image_jpeg, at, evidence_path)
        ms = round((time.perf_counter() - t0) * 1000)
        extra = label.extra or {}
        eng = getattr(self.watcher, "engine", None)
        zones = (eng.device.get("privacy_zones") if eng is not None else None) or []
        self.trace.mark(
            "vision", model=extra.get("vision_model") or self.model_id,
            ms=extra.get("vision_ms") or ms, cached=bool(extra.get("vision_cached")),
            package_visible=label.package_visible, person_present=label.person_present,
            confidence=label.confidence, note=label.note,
            privacy_zones_masked=len(zones),
            faces_pixelated=getattr(self.watcher, "faces_redacted", None))
        return label


class LiveResponder(Responder):
    """The normal ladder, minus the +5 min re-call and the neighbor/family rungs unless the
    run was started with ``full_ladder``."""

    def __init__(self, *args: Any, full_ladder: bool = False, trace: LiveTrace | None = None,
                 **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.full_ladder = full_ladder
        self.trace = trace

    def _skip(self, what: str) -> None:
        if self.trace is not None:
            self.trace.mark("skipped", what=what, how="run with --full-ladder to allow it")

    def _recall(self, inc, finding, now):  # type: ignore[override]
        if self.full_ladder:
            return super()._recall(inc, finding, now)
        if inc.patient_at is not None and now - inc.patient_at >= timedelta(minutes=5):
            self._skip("second call to Rosa (+5 min)")
        return []

    def _climb(self, inc, finding, now):  # type: ignore[override]
        if self.full_ladder:
            return super()._climb(inc, finding, now)
        return []


# ---------------------------------------------------------------------------------------
# the run
# ---------------------------------------------------------------------------------------


class LiveRun:
    """Arms the engine for a live run and drives the chosen trigger until ``minutes`` pass.

    ``voice`` and ``notifier`` are the real channels (built from the environment by the API);
    they are always wrapped in the caps above, and replaced by console-only channels in a dry
    run or a rehearsal.
    """

    def __init__(self, engine: Engine, live: Any, watcher: Any, opts: LiveOptions, *,
                 voice: Any = None, notifier: Any = None, out_dir: Path | None = RUNS_DIR,
                 tick_s: float = 5.0) -> None:
        self.engine, self.live, self.watcher, self.opts = engine, live, watcher, opts
        self.real_voice, self.real_notifier = voice, notifier
        self.out_dir = out_dir
        self.tick_s = tick_s
        self.trace = LiveTrace(opts, out_dir=out_dir)
        self.tasks: list[asyncio.Task] = []
        self.voice: CappedVoice | None = None
        self.notifier: CappedNotifier | None = None
        self._listening = False

    @property
    def active(self) -> bool:
        return self.trace.active

    def _on_record(self, record: dict[str, Any]) -> None:
        if self.trace.active:
            self.trace.on_record(record)
            if record.get("kind") in ("finding", "action"):
                self.trace.save()

    def arm(self) -> None:
        """Reset the engine to a live day: wall clock, an insulin delivery expected now, the
        capped channels and the traced vision. Synchronous and offline (no Ring/AWS calls)."""
        from .notify import ConsoleNotifier

        eng, o = self.engine, self.opts
        eng.reset()
        eng.clock = ZonedWallClock(eng.household.patient.timezone)
        if hasattr(eng.ambient, "override_c"):
            eng.ambient.override_c = o.ambient_c
        if o.device_id:
            eng.device["id"] = o.device_id
        eng.device["source"] = "ring_playground_replay" if o.rehearsal else "ring_live"
        now = eng.clock.now()
        eng.add_expectation(Expectation(
            ExpectationKind.MEDICATION_DELIVERY, "Insulin refill (pharmacy)",
            now - timedelta(minutes=15), now + timedelta(hours=3), carrier="Courier",
            tracking="LIVE-RUN", medication=MedicationProfile(),
            notes="Live run: delivery window set around now"))

        offline = o.dry_run or o.rehearsal
        voice = None if offline or self.real_voice is None else CappedVoice(
            self.real_voice, o.max_calls, self.trace)
        notifier = CappedNotifier(ConsoleNotifier() if offline or self.real_notifier is None
                                  else self.real_notifier, o.max_sms, self.trace)
        self.voice, self.notifier = voice, notifier
        old = eng.responder
        responder = LiveResponder(eng.household, notifier, old.writer, voice=voice,
                                  full_ladder=o.full_ladder, trace=self.trace)
        responder.on_update = eng.ledger.update_action
        eng.responder = responder

        if self.watcher is not None:
            if not isinstance(self.watcher.vision, TracedVision):
                self.watcher.vision = TracedVision(self.watcher.vision, self.trace, self.watcher)
            else:
                self.watcher.vision.trace = self.trace
        self.live.watcher = self.watcher
        self.live.trace = self.trace
        self.live.seen_events.clear()
        if not self._listening:
            eng.ledger.subscribe(self._on_record)
            self._listening = True

        self.trace.ends_at = _now() + timedelta(minutes=o.minutes)
        self.trace.device = {"id": f"…{str(eng.device.get('id') or '')[-6:]}"
                             if eng.device.get("id") else None,
                             "name": eng.device.get("name")}
        self.trace.mark("armed", trigger=o.trigger, dry_run=offline,
                        rehearsal=o.rehearsal or None,
                        call_placed_by="Amazon Connect" if voice else None,
                        sms_by=notifier.channel,
                        caps=f"{o.max_calls} call, {o.max_sms} SMS"
                             + ("" if o.full_ladder else "; no re-call, no Luis/Ana"),
                        ambient_c=o.ambient_c)
        self.trace.save()

    async def start(self) -> None:
        self.arm()
        o = self.opts
        poll_acts = o.trigger in ("history", "both")
        self.tasks = [
            asyncio.create_task(self._guard(self.live._poll_history_loop(
                interval=o.poll_s, act=poll_acts, snapshots=o.snapshots,
                whep_followup=o.whep_followup), "history poller")),
            asyncio.create_task(self._ticker()),
            asyncio.create_task(self._timer()),
        ]
        if o.trigger in ("whep", "both"):
            self.tasks.append(asyncio.create_task(self._guard(self.live._watch_loop(),
                                                              "WHEP watch")))
        # device name/id resolved by the poller's first device lookup
        asyncio.get_running_loop().call_later(5, self._refresh_device)

    def _refresh_device(self) -> None:
        d = self.engine.device
        if d.get("id"):
            self.trace.device = {"id": f"…{str(d['id'])[-6:]}", "name": d.get("name"),
                                 "online": d.get("online"), "encrypted": d.get("encrypted")}

    async def _guard(self, coro, what: str) -> None:
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("%s crashed", what)
            self.trace.mark("error", what=f"{what} stopped: {str(exc)[:160]}")

    async def _ticker(self) -> None:
        """Time moves on a porch: re-evaluate so 'at risk' findings appear on schedule."""
        while True:
            await asyncio.sleep(self.tick_s)
            try:
                self.engine.evaluate()
            except Exception:
                log.exception("evaluate failed")

    async def _timer(self) -> None:
        await asyncio.sleep(self.opts.minutes * 60)
        await self.stop("time limit reached")

    async def stop(self, reason: str = "stopped") -> Path | None:
        current = asyncio.current_task()
        for t in self.tasks:
            if t is not current and not t.done():
                t.cancel()
        return self.finalize(reason)

    def finalize(self, reason: str) -> Path | None:
        """Close the trace (no event loop needed) and save it."""
        if self.trace.active:
            self.trace.mark("stopped", reason=reason, **self.trace.counts)
            self.trace.stopped_at = _now()
            log.info("live run %s stopped (%s)", self.trace.run_id, reason)
        return self.trace.save()

    def to_api(self) -> dict[str, Any]:
        self._refresh_device()
        return self.trace.to_api()
