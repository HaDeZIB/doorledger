"""Place Rosa's minute-0 alert for real: the Spanish voice call (Amazon Connect) and the SMS
(Amazon SNS), through DoorLedger's own code path. Made for filming the phone ringing.

What it does, and what it does NOT do:

* builds the same porch finding the engine raises when Ring sees the insulin on the step, and
  hands it to the engine's ``Responder.contact()`` with the engine's notifier classes
  (``ConnectVoiceNotifier`` + ``SNSNotifier``). The words come from the fixed templates in
  ``core/src/doorledger/wording.py``; no LLM is involved;
* sends ONE contact: minute 0 only. It never runs the engine or the ladder, so there is no
  +5 min re-call and no text to Luis or Ana during the take;
* the call goes only to ``DOORLEDGER_VOICE_TO`` and the SMS only to ``DOORLEDGER_SMS_TO`` (the
  one verified test phone), exactly as in the app. It refuses to run if they are not set;
* prints the Connect contact id, then polls ``describe_contact`` for about 60 s and prints
  ``answered`` or ``no_answer``. Phone numbers are always masked (last 2 digits only).

    uv run --package doorledger python scripts/place_patient_alert.py --dry-run
    uv run --package doorledger python scripts/place_patient_alert.py            # call + SMS
    uv run --package doorledger python scripts/place_patient_alert.py --call     # call only
    uv run --package doorledger python scripts/place_patient_alert.py --kind too_late

``.env`` in the repository root is read first (values already in the environment win), so
the same ``DOORLEDGER_*`` settings the API uses apply here. ``--dry-run`` sends nothing.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import threading
import time
from collections.abc import Callable, MutableMapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from doorledger.domain import Action, Finding, FindingKind, Severity
from doorledger.household import demo_household
from doorledger.notify import ConnectVoiceNotifier, ConsoleNotifier, SNSNotifier, demo_envelope
from doorledger.responder import Responder, TemplateWriter

ROOT = Path(__file__).resolve().parents[1]

# --kind → (responder purpose, the finding the engine would raise)
KINDS: dict[str, tuple[str, FindingKind, Severity, dict[str, Any]]] = {
    # Ring just saw the insulin on a step at −9 °C (the demo's 14:07 alert)
    "porch_cold": ("porch_patient", FindingKind.PACKAGE_EXPOSED, Severity.INFO,
                   {"minutes_on_porch": 0.0, "estimated_internal_c": 5.0}),
    # it was outside too long: keep it, call the pharmacy or Ana before using it
    "too_late": ("porch_compromised", FindingKind.PACKAGE_COMPROMISED, Severity.CRITICAL,
                 {"minutes_on_porch": 55.0, "estimated_internal_c": -1.2}),
}
CONNECT_VARS = ("DOORLEDGER_CONNECT_INSTANCE_ID", "DOORLEDGER_CONNECT_FLOW_ID",
                "DOORLEDGER_CONNECT_SOURCE_NUMBER", "DOORLEDGER_VOICE_TO")
PHONE_VARS = {"DOORLEDGER_VOICE_TO", "DOORLEDGER_SMS_TO", "DOORLEDGER_CONNECT_SOURCE_NUMBER"}
ENV_VARS = (*CONNECT_VARS, "DOORLEDGER_SMS_TO", "DOORLEDGER_CONNECT_REGION", "AWS_REGION",
            "AWS_PROFILE")
_PHONE = re.compile(r"\+?\d[\d\s().-]{6,}\d")


def mask(value: str) -> str:
    """'+5218331234567' → '+***********67': only the last 2 digits are ever shown."""
    digits = re.sub(r"\D", "", value)
    if len(digits) <= 2:
        return "*" * len(digits)
    return ("+" if value.strip().startswith("+") else "") + "*" * (len(digits) - 2) + digits[-2:]


def mask_text(text: str) -> str:
    return _PHONE.sub(lambda m: mask(m.group(0)), text)


class _MaskPhones(logging.Filter):
    """Keeps phone numbers out of log lines (boto errors can echo the destination)."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg, record.args = mask_text(record.getMessage()), ()
        return True


def load_env(path: Path, environ: MutableMapping[str, str]) -> bool:
    """Minimal .env reader (KEY=VALUE, # comments, optional quotes and ``export``), like
    ``uv run --env-file .env``. Never overrides a variable that is already set."""
    if not path.is_file():
        return False
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.removeprefix("export ").split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        if key and value and not environ.get(key):
            environ[key] = value
    return True


def env_report(environ: MutableMapping[str, str]) -> list[str]:
    lines = []
    for k in ENV_VARS:
        v = environ.get(k, "")
        shown = "not set" if not v else (f"set ({mask(v)})" if k in PHONE_VARS
                                         else (f"set ({v})" if k in ("AWS_REGION", "AWS_PROFILE",
                                                                      "DOORLEDGER_CONNECT_REGION")
                                               else "set"))
        lines.append(f"  {k:<34} {shown}")
    return lines


def build_finding(kind: str, now: datetime) -> tuple[str, Finding]:
    purpose, fkind, severity, extra = KINDS[kind]
    data = {"direction": "cold", "ambient_c": -9.0, "status": "safe", **extra}
    summary = ("Ring saw the insulin left on the porch (filming trigger)." if kind == "porch_cold"
               else "The insulin was outside too long (filming trigger).")
    return purpose, Finding(fkind, severity, now, summary, "FILMING", data=data)


def main(argv: list[str] | None = None, *, environ: MutableMapping[str, str] | None = None,
         connect_client: Any = None, sns_client: Any = None,
         sleep: Callable[[float], None] = time.sleep, out: TextIO | None = None) -> int:
    out = out or sys.stdout
    env = os.environ if environ is None else environ

    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    which = p.add_mutually_exclusive_group()
    which.add_argument("--call", action="store_true", help="voice call only (Amazon Connect)")
    which.add_argument("--sms", action="store_true", help="SMS only (Amazon SNS)")
    which.add_argument("--both", action="store_true",
                       help="call and SMS in the same contact, as the engine does (default)")
    p.add_argument("--kind", choices=sorted(KINDS), default="porch_cold",
                   help="porch_cold: the 14:07 alert (default); too_late: the 'outside too "
                        "long' alert")
    p.add_argument("--dry-run", action="store_true",
                   help="print the exact SSML and SMS and which settings are present; send "
                        "nothing")
    p.add_argument("--wait", type=float, default=60.0,
                   help="seconds to poll describe_contact for the call outcome (default 60)")
    p.add_argument("--countdown", type=int, default=3,
                   help="seconds to wait before sending, to cue the camera (default 3)")
    p.add_argument("--env-file", type=Path, default=ROOT / ".env")
    args = p.parse_args(argv)
    say = lambda s="": print(mask_text(s), file=out, flush=True)

    handler = logging.StreamHandler(out)
    handler.addFilter(_MaskPhones())
    handler.setFormatter(logging.Formatter("  log: %(message)s"))
    log = logging.getLogger("doorledger")
    saved = (log.handlers[:], log.level, log.propagate)
    log.handlers[:], log.propagate = [handler], False
    log.setLevel(logging.WARNING)
    try:
        return _run(args, env, say, out, connect_client, sns_client, sleep)
    finally:
        log.handlers[:], log.propagate = saved[0], saved[2]
        log.setLevel(saved[1])


def _run(args: argparse.Namespace, env: MutableMapping[str, str], say: Callable[..., None],
         out: TextIO, connect_client: Any, sns_client: Any,
         sleep: Callable[[float], None]) -> int:
    loaded = load_env(args.env_file, env)
    chans = ["voice"] if args.call else ["sms"] if args.sms else ["voice", "sms"]
    hh = demo_household()
    rosa = hh.by_role("patient")[0]
    if rosa.phone:  # never: every demo message goes to the one verified test phone
        say("refusing: the demo patient has her own phone number set")
        return 2
    purpose, finding = build_finding(args.kind, datetime.now(UTC))

    say(f"DoorLedger patient alert · kind={args.kind} ({purpose}) · "
        f"channels={' + '.join(chans)} · .env {'loaded' if loaded else 'not found'}")
    say("Settings:")
    for line in env_report(env):
        say(line)

    if args.dry_run:
        # Same Responder and templates, but no Connect and a console notifier: nothing leaves.
        dry = Responder(hh, ConsoleNotifier(), TemplateWriter(), voice=None)
        actions = dry.contact("notify", rosa, finding, purpose, None, finding.at, channels=chans)
        for a in actions:
            if a.data.get("channel") == "voice":
                say("\nCALL (Amazon Connect contact attribute `ssml`, spoken by the contact flow):")
                say(f"  text: {a.message}")
                say(f"  ssml: {a.data['ssml']}")
            else:
                say("\nSMS (exact body SNSNotifier publishes):")
                say(f"  {demo_envelope(rosa, a.message)[:600]}")
        say("\nDry run: nothing was sent. No +5 re-call and no texts to Luis or Ana are ever "
            "sent by this script.")
        return 0

    missing = []
    if "voice" in chans:
        missing += [k for k in CONNECT_VARS if not env.get(k)]
    if "sms" in chans and not env.get("DOORLEDGER_SMS_TO"):
        missing.append("DOORLEDGER_SMS_TO")
    if missing:
        say(f"refusing to send: not set: {', '.join(missing)}")
        return 2

    region = env.get("AWS_REGION", "us-east-1")
    done = threading.Event()
    outcome: dict[str, str] = {}
    voice = None
    if "voice" in chans:
        voice = ConnectVoiceNotifier(
            instance_id=env["DOORLEDGER_CONNECT_INSTANCE_ID"],
            flow_id=env["DOORLEDGER_CONNECT_FLOW_ID"],
            source=env["DOORLEDGER_CONNECT_SOURCE_NUMBER"], to=env["DOORLEDGER_VOICE_TO"],
            region=env.get("DOORLEDGER_CONNECT_REGION", region), client=connect_client,
            poll_for_s=args.wait, poll_every_s=3.0, sleep=sleep)
    if "sms" in chans:
        notifier: Any = SNSNotifier(phone=env["DOORLEDGER_SMS_TO"], region=region)
        notifier._client = sns_client  # None: boto3 client created on first send
    else:
        notifier = ConsoleNotifier()  # call only: if the call fails, nothing is texted

    def on_update(action: Action) -> None:
        outcome["status"] = str(action.data.get("status"))
        done.set()

    responder = Responder(hh, notifier, TemplateWriter(), voice=voice, on_update=on_update)
    for n in range(args.countdown, 0, -1):
        say(f"sending in {n}…")
        sleep(1)
    actions = responder.contact("notify", rosa, finding, purpose, None, finding.at,
                                channels=chans)
    contact_id = None
    for a in actions:
        if a.data.get("channel") == "voice":
            contact_id = a.data.get("contact_id")
            say(f"CALL  {a.data.get('status')}  → {mask(env['DOORLEDGER_VOICE_TO'])}")
            if contact_id:  # printed as is (an id, not a number)
                print(f"      Amazon Connect contact id: {contact_id}", file=out, flush=True)
        elif a.data.get("fallback_for") == "voice":
            say("CALL  failed; the SMS fallback was not sent (call-only mode)")
        else:
            sent = a.delivered and isinstance(notifier, SNSNotifier)
            say(f"SMS   {'accepted by Amazon SNS' if sent else 'NOT sent'}  → "
                f"{mask(env.get('DOORLEDGER_SMS_TO', ''))}")
    if contact_id is None:
        return 0 if all(a.delivered for a in actions) else 1

    say(f"waiting up to {args.wait:.0f} s for the call outcome (describe_contact)…")
    done.wait(args.wait + 5)
    status = outcome.get("status")
    say(f"CALL  outcome: {status or 'unknown (still ringing, or no status yet)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
