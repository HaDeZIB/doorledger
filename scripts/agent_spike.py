"""Spike S5: run the full_day scenario headless, then exercise CareAgent on Bedrock.

    DOORLEDGER_WRITER=template DOORLEDGER_PERCEPTION=off \
        uv run --package doorledger python scripts/agent_spike.py [--models m1,m2] [--handle]

Only the agent calls Bedrock (messages use templates, perception is off). Prints JSON lines.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, time
from zoneinfo import ZoneInfo

os.environ.setdefault("DOORLEDGER_WRITER", "template")
os.environ.setdefault("DOORLEDGER_PERCEPTION", "off")

from doorledger import api
from doorledger.agent import CareAgent, replay_scenario
from doorledger.clock import SimClock
from doorledger.domain import Observation, ObservationKind, Source, utcnow
from doorledger.engine import Engine
from doorledger.household import demo_household
from doorledger.ledger import Ledger
from doorledger.notify import ConsoleNotifier
from doorledger.responder import Responder, TemplateWriter
from doorledger.scenarios import day_plan
from doorledger.weather import AmbientTemperature
from fastapi.testclient import TestClient

QUESTIONS = [
    "Did Maria come today?",
    "Is mom's insulin ok?",
    "Why did you text Luis?",
    "Did mom take her blood pressure pills this morning?",
]


def emit(label, reply):
    print(json.dumps({"label": label, "model": reply.model, "latency_ms": reply.latency_ms,
                      "usage": reply.usage, "tools": [c["name"] for c in reply.tool_calls],
                      "text": reply.text}, ensure_ascii=False), flush=True)


class SilentResponder(Responder):
    """Rules disabled so handle() decides alone (guardrails still apply)."""

    def handle(self, finding, now):
        return []

    def followup(self, porch_findings, now):
        return []


def handle_demo(models):
    tz = ZoneInfo("America/New_York")
    day = datetime.now(tz)
    at = lambda h, m: datetime.combine(day.date(), time(h, m), tzinfo=tz)
    hh = demo_household()
    eng = Engine(hh, Ledger(household=hh.id), SilentResponder(hh, ConsoleNotifier(), TemplateWriter()),
                 SimClock(utcnow(), 0.0), AmbientTemperature(hh.lat, hh.lon, override_c=34.0))
    for e in day_plan(day, tz):
        eng.add_expectation(e)
    ca = CareAgent(eng, models=models)
    # 1) missed visit at 09:50
    eng.clock.set(at(9, 50), 0.0)
    r = eng.evaluate()
    f = next(f for f in r.findings if f.kind == "missed_visit")
    emit("handle:missed_visit", ca.handle(f))
    # 2) insulin at risk at 15:17 (dropped 14:07)
    eng.ingest(Observation(ObservationKind.PACKAGE_DROPPED, at(14, 7), Source.RING_LIVE,
                           evidence_path="evidence/package.jpg"))
    eng.clock.set(at(15, 17), 0.0)
    r = eng.evaluate()
    f = next(f for f in r.findings if f.kind == "package_at_risk")
    emit("handle:package_at_risk", ca.handle(f))
    for a in eng.ledger.records(kinds=["action"]):
        b = a["body"]
        print(json.dumps({"action": b["kind"], "to": b["target"], "msg": b["message"],
                          "origin": b["data"].get("origin")}, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="")
    ap.add_argument("--handle", action="store_true")
    ap.add_argument("--api", action="store_true", help="also hit /api/ask and /api/summary")
    args = ap.parse_args()
    models = [m for m in args.models.split(",") if m] or None

    replay_scenario(api.engine, "full_day")
    ca = CareAgent(api.engine, models=models)
    for q in QUESTIONS:
        emit(f"ask:{q}", ca.ask(q))
    emit("summary", ca.daily_summary())
    if args.api:
        c = TestClient(api.app)
        print(json.dumps(c.post("/api/ask", json={"question": QUESTIONS[0]}).json(),
                         ensure_ascii=False))
        print(json.dumps(c.get("/api/summary").json(), ensure_ascii=False))
    if args.handle:
        handle_demo(models)


if __name__ == "__main__":
    main()
