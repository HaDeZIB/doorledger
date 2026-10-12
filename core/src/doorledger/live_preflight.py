"""Before a live run: check everything without placing a call, and learn what the Playground emits.

* ``run_preflight``: token (and minutes left), device, history, a snapshot at the newest event,
  one Amazon Nova 2 Lite call on that snapshot, AWS credentials, the Amazon Connect flow and
  the SNS sandbox destination (read-only APIs only). Never prints a token, phone number,
  Connect id or AWS account id.
* ``probe``: read-only. Polls Ring history while you click "Package" in the Playground and
  prints each new row as it appears (type, Ring start, open/closed, how late it showed up)
  plus whether a snapshot at its start works. That tells which live trigger to use.
* ``PlaygroundReplayRing``: an offline stand-in built from recorded Playground responses, used
  by ``scripts/live_demo.py --rehearse`` and the tests. It "clicks Package" a few seconds in.
"""

from __future__ import annotations

import base64
import json
import os
import re
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
PLAYGROUND_FIXTURES = ROOT / "fixtures" / "playground"
PACKAGE_FRAME = ROOT / "fixtures" / "ring_playground" / "package" / "frames" / "0000.jpg"
E164 = re.compile(r"^\+[1-9]\d{7,14}$")
CONNECT_VARS = ("DOORLEDGER_CONNECT_INSTANCE_ID", "DOORLEDGER_CONNECT_FLOW_ID",
                "DOORLEDGER_CONNECT_SOURCE_NUMBER", "DOORLEDGER_VOICE_TO")


# ---------------------------------------------------------------------------------------
# offline Playground (rehearsal and tests)
# ---------------------------------------------------------------------------------------


class PlaygroundReplayRing:
    """Async Ring client stand-in: the recorded Playground device and history, plus one new
    ``on_demand`` row ``click_after_s`` seconds after creation (the "Package" click), and the
    recorded Playground Package frame as every snapshot. No network, no token."""

    def __init__(self, *, fixtures: Path = PLAYGROUND_FIXTURES, frame: Path = PACKAGE_FRAME,
                 click_after_s: float = 6.0, row_lag_s: float = 0.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        from ringpartner import AsyncRingClient
        from ringpartner.fixtures import AsyncReplayTransport

        self._client = AsyncRingClient("replay", transport=AsyncReplayTransport(fixtures))
        self.frame = frame.read_bytes()
        self.click_after_s, self.row_lag_s = click_after_s, row_lag_s
        self.clock = clock
        self.t0 = clock()
        self.click_at: datetime | None = None
        self.snapshots: list[datetime | None] = []

    async def devices(self):
        return await self._client.devices()

    async def history(self, device_id: str, event_types=None, page_key=None):
        from ringpartner.models import HistoryEvent, HistoryPage

        page = await self._client.history(device_id)  # recorded rows (all older than "now")
        elapsed = self.clock() - self.t0
        events = list(page.events)
        if elapsed >= self.click_after_s:
            if self.click_at is None:
                self.click_at = datetime.now(UTC) - timedelta(
                    seconds=elapsed - self.click_after_s)
            if elapsed >= self.click_after_s + self.row_lag_s:
                events.insert(0, HistoryEvent("ava1.ring.history.event.REHEARSAL", "on_demand",
                                              self.click_at, None, device_id))
        if event_types:
            events = [e for e in events if e.event_type in event_types]
        return HistoryPage(events, None)

    async def snapshot(self, device_id: str, *, at=None, **_: Any):
        from ringpartner.models import Media

        self.snapshots.append(at)
        return Media(self.frame, "image/jpeg", at, "replay")

    async def aclose(self) -> None:
        await self._client.aclose()


# ---------------------------------------------------------------------------------------
# preflight
# ---------------------------------------------------------------------------------------


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    critical: bool = True

    def line(self) -> str:
        mark = "OK  " if self.ok else ("FAIL" if self.critical else "WARN")
        return f"[{mark}] {self.name}: {self.detail}"


def _ring_err(exc: Exception) -> str:
    status = getattr(exc, "status", None)
    text = getattr(exc, "title", None) or getattr(exc, "detail", None) or type(exc).__name__
    return f"{status} {text}" if status else str(text)


def token_minutes_left(token: str, now: float | None = None) -> float | None:
    """Minutes until a JWT-shaped token's ``exp``; None if it isn't a JWT (never printed)."""
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        pad = "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(parts[1] + pad))
        exp = float(claims["exp"])
    except (ValueError, KeyError, TypeError):
        return None
    return (exp - (now if now is not None else time.time())) / 60


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) != 0


def _boto(service: str):
    import boto3

    region = (os.environ.get("DOORLEDGER_CONNECT_REGION") if service == "connect" else None) \
        or os.environ.get("AWS_REGION", "us-east-1")
    return boto3.client(service, region_name=region)


def _aws_error(exc: Exception) -> str:
    """The error code only: AWS messages can quote ARNs and the account id."""
    code = getattr(exc, "response", {}).get("Error", {}).get("Code") if hasattr(
        exc, "response") else None
    return code or type(exc).__name__


def run_preflight(env: dict[str, str] | None = None, *, ring_factory: Callable | None = None,
                  boto: Callable[[str], Any] = _boto, bedrock: bool = True, dry_run: bool = False,
                  port: int = 8787, save_dir: Path | None = None) -> list[Check]:
    """Every check a live run depends on. Read-only: no call, no SMS, no WHEP session."""
    env = dict(os.environ if env is None else env)
    checks: list[Check] = []
    add = checks.append
    send_checks_critical = not dry_run

    # -- Ring -------------------------------------------------------------------------
    token = env.get("RING_ACCESS_TOKEN", "")
    snapshot_jpeg: bytes | None = None
    if not token:
        add(Check("Ring token", False, "RING_ACCESS_TOKEN is empty. In the Ring Developer "
                  "Playground generate a token and paste it into .env"))
    else:
        left = token_minutes_left(token)
        if left is None:
            add(Check("Ring token", True, "set (expiry not readable; Playground tokens last "
                      "about 30 min)", critical=False))
        elif left <= 0:
            add(Check("Ring token", False, "expired: generate a new one in the Playground"))
        else:
            add(Check("Ring token", left >= 12, f"about {left:.0f} min left"
                      + ("" if left >= 12 else ": generate a fresh one before recording"),
                      critical=False))
        from ringpartner import RingClient
        from ringpartner.errors import RingError, RingUnauthorized

        make = ring_factory or (lambda t: RingClient(t))
        ring = make(token)
        try:
            devices = ring.devices()
            add(Check("Ring devices", bool(devices), f"{len(devices)} device(s)"))
            wanted = env.get("RING_DEVICE_ID") or None
            device = next((d for d in devices if d.id == wanted), None) if wanted else (
                devices[0] if devices else None)
            if device is None:
                add(Check("Ring device", False, "RING_DEVICE_ID not found on this account"
                          if wanted else "no device on this account"))
            else:
                add(Check("Ring device", not device.is_encrypted,
                          f"{device.name or '?'} (…{device.id[-6:]}), online="
                          f"{device.online}, end-to-end encrypted={device.is_encrypted}"
                          + (" — video analysis is impossible" if device.is_encrypted else "")))
                page = ring.history(device.id)
                newest = max((e for e in page.events if e.start), key=lambda e: e.start,
                             default=None)
                if newest is None:
                    add(Check("Ring history", True, "readable, no rows yet (click any scene "
                              "in the Playground once)", critical=False))
                else:
                    age = (datetime.now(UTC) - newest.start).total_seconds() / 60
                    add(Check("Ring history", True, f"{len(page.events)} row(s); newest "
                              f"{newest.event_type}, {age:.0f} min ago"))
                    try:
                        media = ring.snapshot(device.id, at=newest.start)
                        snapshot_jpeg = media.content
                        where = ""
                        if save_dir is not None:
                            save_dir.mkdir(parents=True, exist_ok=True)
                            (save_dir / "preflight_snapshot.jpg").write_bytes(media.content)
                            where = f", saved to {save_dir / 'preflight_snapshot.jpg'}"
                        add(Check("Ring snapshot at the newest event", True,
                                  f"{len(media.content)} bytes{where}", critical=False))
                    except RingError as exc:
                        add(Check("Ring snapshot at the newest event", False,
                                  _ring_err(exc)
                                  + ": the history trigger will fall back to the live view",
                                  critical=False))
        except RingUnauthorized:
            add(Check("Ring devices", False, "401: the token expired or is wrong. Generate a "
                      "new one in the Playground and paste it into .env"))
        except RingError as exc:
            add(Check("Ring devices", False, _ring_err(exc)))
        finally:
            ring.close()

    try:
        import aiortc  # noqa: F401

        add(Check("WHEP live view support", True, "aiortc installed", critical=False))
    except ImportError:
        add(Check("WHEP live view support", False, "aiortc missing: `uv sync --all-packages`"
                  " (only the whep trigger needs it)", critical=False))

    # -- AWS ----------------------------------------------------------------------------
    try:
        boto("sts").get_caller_identity()  # account id deliberately not printed
        add(Check("AWS credentials", True, f"valid (region {env.get('AWS_REGION', 'us-east-1')})"))
    except Exception as exc:  # noqa: BLE001
        add(Check("AWS credentials", False, _aws_error(exc)))

    if bedrock:
        from .vision import DEFAULT_MODEL, BedrockVision

        frame = snapshot_jpeg or PACKAGE_FRAME.read_bytes()
        try:
            vision = BedrockVision()
            t0 = time.perf_counter()
            label = vision.classify(frame, datetime.now(UTC))
            ms = round((time.perf_counter() - t0) * 1000)
            src = "the Ring snapshot" if snapshot_jpeg else "the recorded Playground frame"
            add(Check("Amazon Nova 2 Lite (Bedrock)", True,
                      f"{DEFAULT_MODEL} on {src}: package_visible={label.package_visible}, "
                      f"{ms} ms"))
        except Exception as exc:  # noqa: BLE001
            add(Check("Amazon Nova 2 Lite (Bedrock)", False, _aws_error(exc)))

    # -- Amazon Connect (voice) and SNS (SMS): configuration + read-only lookups ----------
    missing = [v for v in CONNECT_VARS if not env.get(v)]
    if missing:
        add(Check("Amazon Connect config", False, "missing " + ", ".join(missing),
                  critical=send_checks_critical))
    else:
        bad = [v for v in ("DOORLEDGER_VOICE_TO", "DOORLEDGER_CONNECT_SOURCE_NUMBER")
               if not E164.match(env[v])]
        if bad:
            add(Check("Amazon Connect config", False, "not E.164 (+country…): " + ", ".join(bad),
                      critical=send_checks_critical))
        else:
            try:
                flow = boto("connect").describe_contact_flow(
                    InstanceId=env["DOORLEDGER_CONNECT_INSTANCE_ID"],
                    ContactFlowId=env["DOORLEDGER_CONNECT_FLOW_ID"])["ContactFlow"]
                add(Check("Amazon Connect flow", True, f"'{flow.get('Name', '?')}' "
                          f"({flow.get('State', '?')}); calls go only to DOORLEDGER_VOICE_TO"))
            except Exception as exc:  # noqa: BLE001
                add(Check("Amazon Connect flow", False, _aws_error(exc),
                          critical=send_checks_critical))
    sms_to = env.get("DOORLEDGER_SMS_TO", "")
    if not sms_to:
        add(Check("Amazon SNS config", False, "DOORLEDGER_SMS_TO is empty",
                  critical=send_checks_critical))
    elif not E164.match(sms_to):
        add(Check("Amazon SNS config", False, "DOORLEDGER_SMS_TO is not E.164",
                  critical=send_checks_critical))
    else:
        try:
            sns = boto("sns")
            sandbox = sns.get_sms_sandbox_account_status().get("IsInSandbox")
            verified = None
            if sandbox:
                nums = sns.list_sms_sandbox_phone_numbers().get("PhoneNumbers", [])
                verified = any(n.get("PhoneNumber") == sms_to and n.get("Status") == "Verified"
                               for n in nums)
            add(Check("Amazon SNS SMS", verified is not False,
                      "sandbox, destination verified" if verified else
                      "sandbox, destination NOT verified" if sandbox else "production account",
                      critical=send_checks_critical))
        except Exception as exc:  # noqa: BLE001
            add(Check("Amazon SNS SMS", False, _aws_error(exc), critical=False))

    add(Check("API port", _port_free(port), f"{port} free" if _port_free(port) else
              f"{port} is in use: stop the other DoorLedger API first", critical=True))
    return checks


def preflight_ok(checks: list[Check]) -> bool:
    return all(c.ok or not c.critical for c in checks)


# ---------------------------------------------------------------------------------------
# probe: what does the Playground record when you click "Package"?
# ---------------------------------------------------------------------------------------


def probe(ring, device_id: str, *, seconds: float = 120.0, every: float = 2.0,
          out: Callable[[str], None] = print, save_dir: Path | None = None,
          sleep: Callable[[float], None] = time.sleep,
          clock: Callable[[], float] = time.monotonic) -> list[dict[str, Any]]:
    """Read-only. Prints every NEW history row (all types) as it appears, how many seconds
    after its own start Ring published it, whether it was still open (no ``end``), and
    whether a snapshot at its start works. Returns the rows seen."""
    from ringpartner.errors import RingError

    known = {e.id for e in ring.history(device_id).events}
    started = clock()
    seen: list[dict[str, Any]] = []
    out(f"watching Ring history for {seconds:.0f} s — click 'Package' in the Playground now")
    while clock() - started < seconds:
        sleep(every)
        try:
            page = ring.history(device_id)
        except RingError as exc:
            out(f"  history failed: {_ring_err(exc)}")
            continue
        for e in sorted((e for e in page.events if e.id not in known and e.start),
                        key=lambda e: e.start):
            known.add(e.id)
            now = datetime.now(UTC)
            row = {"event_type": e.event_type, "start": e.start.isoformat(),
                   "end": e.end.isoformat() if e.end else None,
                   "published_after_s": round((now - e.start).total_seconds(), 1),
                   "seen_at_s": round(clock() - started, 1)}
            try:
                media = ring.snapshot(device_id, at=e.start)
                row["snapshot"] = f"ok, {len(media.content)} bytes"
                if save_dir is not None:
                    save_dir.mkdir(parents=True, exist_ok=True)
                    name = f"probe_{len(seen):02d}_{e.event_type}.jpg"
                    (save_dir / name).write_bytes(media.content)
                    row["snapshot"] += f" -> {save_dir / name}"
            except RingError as exc:
                row["snapshot"] = _ring_err(exc)
            seen.append(row)
            out(f"  +{row['seen_at_s']:>5}s  {e.event_type:<14} start {e.start:%H:%M:%S}Z  "
                f"{'open' if not e.end else 'closed'}  published {row['published_after_s']} s "
                f"after its start  snapshot: {row['snapshot']}")
    if not seen:
        out("no new history row appeared: use the WHEP trigger (--trigger whep), see "
            "docs/LIVE_DEMO.md")
    else:
        first = seen[0]
        out(f"first new row: {first['event_type']}, published {first['published_after_s']} s "
            f"after it started. History trigger latency ≈ that + the poll interval + ~3 s.")
    return seen
