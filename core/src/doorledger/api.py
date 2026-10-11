"""HTTP API for the dashboard (contract: web/dashboard/API_CONTRACT.md).

Run:  uv run --package doorledger uvicorn doorledger.api:app --port 8787
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from . import evv
from .clock import SimClock
from .domain import utcnow
from .engine import Engine
from .household import demo_household
from .ledger import Ledger
from .notify import default_notifier
from .reconcile import reconcile
from .responder import BedrockWriter, Responder, TemplateWriter
from .scenarios import ScenarioRunner
from .weather import AmbientTemperature

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
log = logging.getLogger("doorledger.api")

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE_DIR = Path(os.environ.get("DOORLEDGER_EVIDENCE", ROOT / "fixtures" / "evidence"))


def build_engine() -> Engine:
    household = demo_household()
    ledger = Ledger(os.environ.get("DOORLEDGER_DB", ":memory:"), household=household.id)
    writer = TemplateWriter() if os.environ.get("DOORLEDGER_WRITER") == "template" else BedrockWriter()
    responder = Responder(household, default_notifier(), writer)
    ambient = AmbientTemperature(household.lat, household.lon)
    return Engine(household, ledger, responder, SimClock(utcnow(), speed=1.0), ambient,
                  device={"id": household.device_id, "name": household.device_name,
                          "online": None, "source": os.environ.get("DOORLEDGER_SOURCE", "replay")})


engine = build_engine()
runner = ScenarioRunner(engine)
app = FastAPI(title="DoorLedger API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("DOORLEDGER_CORS", "http://localhost:3000").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

_subscribers: set[asyncio.Queue] = set()
_loop: asyncio.AbstractEventLoop | None = None


def _broadcast(record: dict[str, Any]) -> None:
    if _loop is None:
        return
    for q in list(_subscribers):
        _loop.call_soon_threadsafe(q.put_nowait, record)


engine.ledger.subscribe(_broadcast)


@app.on_event("startup")
async def _startup() -> None:
    global _loop
    _loop = asyncio.get_running_loop()


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "scenario": runner.name, "now": engine.clock.now().isoformat()}


@app.get("/api/household")
def household() -> dict[str, Any]:
    data = engine.household.to_api()
    data["device"] = engine.device
    data["ambient"] = {"celsius": engine.ambient.current(), "source": engine.ambient.last_source}
    return data


@app.get("/api/state")
def state(at: str | None = None) -> dict[str, Any]:
    when = datetime.fromisoformat(at) if at else None
    return engine.state(when)


@app.get("/api/timeline")
def timeline(since: str | None = None) -> list[dict[str, Any]]:
    return engine.ledger.records(since=datetime.fromisoformat(since) if since else None)


@app.get("/api/stream")
async def stream() -> StreamingResponse:
    q: asyncio.Queue = asyncio.Queue()
    _subscribers.add(q)

    async def gen():
        try:
            yield "retry: 2000\n\n"
            while True:
                try:
                    rec = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(rec)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            _subscribers.discard(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/evidence/{path:path}")
def evidence(path: str) -> FileResponse:
    target = (EVIDENCE_DIR / path.removeprefix("evidence/")).resolve()
    if EVIDENCE_DIR.resolve() not in target.parents or not target.is_file():
        raise HTTPException(404, "evidence not found")
    return FileResponse(target)


@app.get("/api/evv.csv")
def evv_csv(date: str | None = None) -> PlainTextResponse:
    r = reconcile(list(engine.expectations.values()), engine.observations, engine.clock.now(),
                  engine.ambient)
    return PlainTextResponse(evv.to_csv(r, engine.household), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=evv.csv"})


class DemoRun(BaseModel):
    scenario: str
    speed: float = 60.0


@app.post("/api/demo/run")
async def demo_run(body: DemoRun) -> dict[str, Any]:
    try:
        await runner.start(body.scenario, body.speed)
    except KeyError:
        raise HTTPException(400, f"unknown scenario {body.scenario}") from None
    return {"ok": True, "scenario": body.scenario}


@app.post("/api/demo/reset")
def demo_reset() -> dict[str, Any]:
    runner.stop()
    engine.reset()
    return {"ok": True}
