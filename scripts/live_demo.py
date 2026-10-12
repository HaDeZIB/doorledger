"""DoorLedger live end-to-end run: Ring Developer Playground "Package" click -> Rosa's phone.

Step-by-step guide for the recording: docs/LIVE_DEMO.md. The usual order:

  make live-preflight   check token, device, Bedrock, Connect/SNS config (no call, no SMS)
  make live-probe       read-only: click "Package" and see what Ring records, and how fast
  make live-rehearse    offline dress rehearsal (recorded Playground data, no call, no SMS)
  make live-dry         live Ring + Bedrock, but no call and no SMS
  make live             the take: at most 1 call + 1 SMS, only to your verified test phone

Every target runs this script with `uv run --env-file .env`. Options (after `--` in make, or
directly): --trigger history|whep|both, --max-calls N, --max-sms N, --full-ladder,
--minutes M, --ambient-c C|real, --device ID, --port P, --yes.

Safety: a live run places at most --max-calls calls (default 1) to DOORLEDGER_VOICE_TO and
--max-sms SMS (default 1) to DOORLEDGER_SMS_TO. The +5 min re-call and the texts to Luis and
Ana are skipped unless --full-ladder. The API this script serves refuses /api/demo/* while the
run is active, and nothing reachable over HTTP can start a live run.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _ambient(value: str) -> float | None:
    return None if value.lower() in ("real", "open-meteo", "none") else float(value)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--preflight", action="store_true", help="check everything, place nothing")
    mode.add_argument("--probe", action="store_true",
                      help="read-only: print new Ring history rows while you click Package")
    mode.add_argument("--rehearse", action="store_true",
                      help="offline: recorded Playground data + recorded Bedrock labels, no calls")
    p.add_argument("--dry-run", action="store_true", help="live Ring + Bedrock; no call, no SMS")
    p.add_argument("--trigger", choices=("history", "whep", "both"), default="history")
    p.add_argument("--max-calls", type=int, default=1)
    p.add_argument("--max-sms", type=int, default=1)
    p.add_argument("--full-ladder", action="store_true",
                   help="also the +5 min re-call and the texts to Luis and Ana (still capped)")
    p.add_argument("--minutes", type=float, default=10.0, help="stop watching after M minutes")
    p.add_argument("--ambient-c", type=_ambient, default=-9.0,
                   help="outside temperature for the story (default -9), or 'real' (Open-Meteo)")
    p.add_argument("--device", default=os.environ.get("RING_DEVICE_ID"),
                   help="Ring device id (default: RING_DEVICE_ID, else the first device)")
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("--poll", type=float, default=2.0, help="history poll interval, seconds")
    p.add_argument("--snapshots", type=int, default=3, help="snapshots per Ring event")
    p.add_argument("--whep-followup", action="store_true",
                   help="also open a live view after each event's snapshots")
    p.add_argument("--seconds", type=float, default=120.0, help="probe duration")
    p.add_argument("--click-after", type=float, default=8.0,
                   help="rehearsal: seconds until the simulated Package click")
    p.add_argument("--no-bedrock", action="store_true", help="preflight: skip the Nova call")
    p.add_argument("--yes", action="store_true", help="don't ask before a run that sends")
    return p


def cmd_preflight(args, *, quiet: bool = False) -> bool:
    from doorledger.live_preflight import preflight_ok, run_preflight
    from doorledger.live_session import RUNS_DIR

    env = dict(os.environ)
    if args.device:
        env["RING_DEVICE_ID"] = args.device
    checks = run_preflight(env, bedrock=not args.no_bedrock, dry_run=args.dry_run,
                           port=args.port, save_dir=RUNS_DIR)
    for c in checks:
        print(c.line())
    ok = preflight_ok(checks)
    if not quiet:
        print("\nREADY: run `make live`" if ok else "\nNOT READY: fix the FAIL lines above")
    return ok


def cmd_probe(args) -> int:
    from doorledger.live_preflight import probe
    from doorledger.live_session import RUNS_DIR
    from ringpartner import RingClient
    from ringpartner.fixtures import RecordingTransport

    token = os.environ.get("RING_ACCESS_TOKEN")
    if not token:
        print("RING_ACCESS_TOKEN is empty (paste a fresh Playground token into .env)")
        return 2
    # Raw responses are recorded (gitignored) so tomorrow's real Playground behaviour can become
    # an offline test fixture. The token is a request header and is never written.
    rec = RUNS_DIR / "probe_fixtures"
    with RingClient(token, transport=RecordingTransport(rec)) as ring:
        device = args.device or ring.devices()[0].id
        probe(ring, device, seconds=args.seconds, save_dir=RUNS_DIR / "probe")
    print(f"recorded responses: {rec}")
    return 0


def print_summary(trace) -> None:
    data = trace.to_api()
    print(f"\n=== {data['source'].upper()} RUN {data['run_id']} ({data['trigger']} trigger) ===")
    for s in data["steps"]:
        t = s.get("t_ms")
        when = f"{t / 1000:+8.1f} s" if t is not None else "        "
        detail = ", ".join(f"{k}={v}" for k, v in s["detail"].items()
                           if k in ("event_type", "via", "ms", "count", "model", "package_visible",
                                    "observation", "finding", "status", "connect_ms", "delivered",
                                    "api_ms", "what", "reason"))
        print(f"  {when}  {s['step']:<13} {detail}")
    lat = data["latency"]
    print("latency (ms):", {k: v for k, v in lat.items() if v is not None and k.endswith("ms")})
    print("counts:", data["counts"])


def cmd_run(args) -> int:
    from doorledger.live_session import RUNS_DIR, LiveOptions, LiveRun

    rehearse = args.rehearse
    sends = not (rehearse or args.dry_run)
    if not rehearse:
        print("--- preflight ---")
        if not cmd_preflight(args, quiet=True):
            print("\nNOT READY: fix the FAIL lines above (or run with --dry-run to skip sending)")
            return 1
    if sends and not args.yes:
        ladder = "with" if args.full_ladder else "without"
        print(f"\nThis run can place up to {args.max_calls} real call(s) to DOORLEDGER_VOICE_TO "
              f"and {args.max_sms} SMS to DOORLEDGER_SMS_TO, {ladder} the follow-up ladder.")
        if input("Type 'yes' to arm it: ").strip().lower() != "yes":
            print("not armed")
            return 1

    # Environment for the API module, set BEFORE importing it.
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    if rehearse:
        os.environ["DOORLEDGER_PERCEPTION"] = "cache"  # recorded Bedrock labels
        os.environ["DOORLEDGER_WRITER"] = "template"
        for var in ("DOORLEDGER_DYNAMO", "DOORLEDGER_AGENTCORE_ARN"):
            os.environ.pop(var, None)  # offline: nothing goes to AWS
    else:
        os.environ["DOORLEDGER_PERCEPTION"] = "bedrock"
        os.environ["DOORLEDGER_VISION_CACHE"] = str(RUNS_DIR / "vision_cache_live.json")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per poll is noise

    import uvicorn
    from doorledger import api

    opts = LiveOptions(trigger="history" if rehearse else args.trigger,
                       max_calls=args.max_calls, max_sms=args.max_sms,
                       full_ladder=args.full_ladder, dry_run=args.dry_run, rehearsal=rehearse,
                       ambient_c=args.ambient_c, minutes=args.minutes, poll_s=args.poll,
                       snapshots=args.snapshots, whep_followup=args.whep_followup,
                       device_id=args.device)
    run = LiveRun(api.engine, api.live, api.watcher, opts,
                  voice=api.engine.responder.voice, notifier=api.engine.responder.notifier)
    if rehearse:
        from doorledger.live_preflight import PlaygroundReplayRing

        async def replay_ring():
            return PlaygroundReplayRing(click_after_s=args.click_after)

        api.live.ring_factory = replay_ring
    api.live_run = run
    api.app.router.on_startup.append(run.start)

    async def _stop() -> None:
        await run.stop("server stopped")

    api.app.router.on_shutdown.append(_stop)
    what = ("REHEARSAL (offline, recorded Playground data; the 'click' happens "
            f"{args.click_after:.0f} s after start)" if rehearse else
            "DRY RUN (no call, no SMS)" if not sends else "LIVE (sends!)")
    print(f"\n{what}\n  dashboard: run `make dashboard` and open http://localhost:3000"
          f"\n  trace:     http://localhost:{args.port}/api/live/trace"
          + ("" if rehearse else "\n  NOW: click 'Package' in the Ring Developer Playground")
          + "\n  stop:      Ctrl-C\n", flush=True)
    try:
        uvicorn.run(api.app, host="127.0.0.1", port=args.port, log_level="warning",
                    timeout_graceful_shutdown=2)  # the dashboard's SSE stream stays open
    finally:
        run.finalize("interrupted")
        print_summary(run.trace)
        print(f"trace saved under {RUNS_DIR}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.preflight:
        return 0 if cmd_preflight(args) else 1
    if args.probe:
        return cmd_probe(args)
    return cmd_run(args)


if __name__ == "__main__":
    sys.exit(main())
