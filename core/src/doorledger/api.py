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


def build_watcher(eng: Engine):
    """DOORLEDGER_PERCEPTION: bedrock (default; live Bedrock, results also recorded to the
    vision cache) | cache (offline: replay Bedrock's recorded labels for the Ring frames) | off."""
    mode = os.environ.get("DOORLEDGER_PERCEPTION", "bedrock")
    if mode == "off":
        return None
    from .vision import BedrockVision, CachingVision
    from .watcher import Watcher

    cache = ROOT / "fixtures" / "ring_playground" / "vision_cache.json"
    vision = CachingVision(cache, None if mode == "cache" else BedrockVision())
    return Watcher(eng, vision, EVIDENCE_DIR)


watcher = build_watcher(engine)
runner = ScenarioRunner(engine, watcher, ROOT / "fixtures" / "ring_playground")
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
    # Retention: stored evidence frames expire (privacy by default).
    from .watcher import purge_evidence

    days = float(os.environ.get("DOORLEDGER_RETENTION_DAYS", "30"))
    removed = purge_evidence(EVIDENCE_DIR / "captured", days) if (EVIDENCE_DIR / "captured").is_dir() else 0
    if removed:
        log.info("retention: removed %d evidence frames older than %s days", removed, days)


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
                  engine.ambient, in_sun=engine.household.porch_in_sun)
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


# -- CareAgent (Strands on Bedrock): family Q&A + end-of-day summary --------------------------
# Read-only tools only: a question typed into the family app can never send a message.

_care_agent = None


def _agent():
    global _care_agent
    if _care_agent is None:
        from .agent import CareAgent

        _care_agent = CareAgent(engine)
    return _care_agent


class AskBody(BaseModel):
    question: str


@app.post("/api/ask")
def ask(body: AskBody) -> dict[str, Any]:
    if not body.question.strip():
        raise HTTPException(400, "question is empty")
    try:
        return _agent().ask(body.question).to_api("answer")
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)[:300]) from None


@app.get("/api/summary")
def summary() -> dict[str, Any]:
    try:
        return _agent().daily_summary().to_api("summary")
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)[:300]) from None


# --- Ring webhooks, live watching, Caregiver Pass ------------------------------------------

from fastapi import Request  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from ringpartner.webhooks import SIGNATURE_HEADER, InvalidSignature, verify_and_parse  # noqa: E402

from . import presence as _presence  # noqa: E402
from .live import LiveController  # noqa: E402

live = LiveController(engine, watcher, ROOT / "fixtures" / "ring_playground")
PASS_DIR = ROOT / "web" / "caregiver-pass"
if PASS_DIR.is_dir():
    app.mount("/pass", StaticFiles(directory=PASS_DIR, html=True), name="pass")


@app.post("/webhooks/ring")
async def ring_webhook(request: Request) -> dict[str, Any]:
    """Ring partner webhook endpoint. Verify first, parse second, answer fast (<5 s)."""
    key = os.environ.get("RING_HMAC_KEY")
    if not key:
        raise HTTPException(503, "RING_HMAC_KEY not configured")
    raw = await request.body()
    try:
        event = verify_and_parse(key, raw, request.headers.get(SIGNATURE_HEADER))
    except InvalidSignature:
        raise HTTPException(401, "invalid signature") from None
    status = await live.on_webhook(event)
    return {"ok": True, "status": status, "type": event.type, "sub_type": event.sub_type}


@app.post("/api/live/watch")
async def live_watch() -> dict[str, Any]:
    started = live.start_watching()
    return {"ok": True, "started": started, "token": bool(live.token),
            "windows_open": live.windows_open()}


@app.post("/api/live/stop")
def live_stop() -> dict[str, Any]:
    live.stop_watching()
    return {"ok": True}


@app.get("/api/visits/{visit_id}/pass")
def visit_pass(visit_id: str, role: str = "in", request: Request = None) -> dict[str, Any]:  # type: ignore[assignment]
    # Issuing a pass hands out the visit secret, so it is an agency-only operation.
    admin = os.environ.get("DOORLEDGER_ADMIN_TOKEN")
    supplied = request.headers.get("x-admin-token") if request else None
    if not admin or supplied != admin:
        raise HTTPException(401, "agency admin token required (X-Admin-Token)")
    secret = engine.visit_secrets.get(visit_id)
    if secret is None:
        raise HTTPException(404, "unknown visit (start a scenario first)")
    base = str(request.base_url).rstrip("/") if request else "http://localhost:8787"
    url = f"{base}/pass/index.html#v={visit_id}&k={_presence.secret_to_b64url(secret)}&role={role}"
    return {"visit_id": visit_id, "role": role, "url": url}


# --- AWS integrations (optional, env-gated; see docs/aws_architecture.md) -------------------
# DOORLEDGER_DYNAMO=1            mirror every ledger record to DynamoDB (doorledger-ledger)
# DOORLEDGER_AGENTCORE_ARN=arn   answer /api/ask and /api/summary with the CareAgent deployed on
#                                Bedrock AgentCore Runtime (read-only snapshot); falls back to the
#                                in-process Strands agent on any error.

from fastapi.routing import APIRoute

dynamo_mirror = None
if os.environ.get("DOORLEDGER_DYNAMO") == "1":
    try:
        from .aws.dynamo import attach_mirror

        dynamo_mirror = attach_mirror(engine.ledger)
    except Exception as exc:  # noqa: BLE001 — the demo must run without AWS
        log.warning("DynamoDB mirror disabled: %s", str(exc)[:200])

    @app.on_event("shutdown")
    def _flush_dynamo() -> None:
        if dynamo_mirror is not None:
            dynamo_mirror.close(timeout=5)


_agentcore_agent = None
if os.environ.get("DOORLEDGER_AGENTCORE_ARN"):
    from .aws.agentcore import AgentCoreCareAgent

    _agentcore_agent = AgentCoreCareAgent(engine)

    def _replace_route(path: str, method: str) -> None:
        app.router.routes[:] = [r for r in app.router.routes
                                if not (isinstance(r, APIRoute) and r.path == path
                                        and method in r.methods)]

    def _local_fallback(fn, *args: Any) -> dict[str, Any]:
        out = fn(*args)
        out["runtime"] = "local"
        return out

    _replace_route("/api/ask", "POST")
    _replace_route("/api/summary", "GET")

    @app.post("/api/ask")
    def ask_agentcore(body: AskBody) -> dict[str, Any]:
        if not body.question.strip():
            raise HTTPException(400, "question is empty")
        try:
            return _agentcore_agent.ask(body.question)
        except Exception as exc:  # noqa: BLE001 — fall back to the in-process agent
            log.warning("AgentCore ask failed, using local agent: %s", str(exc)[:200])
            out = _local_fallback(ask, body)
            out["agentcore_error"] = str(exc)[:200]
            return out

    @app.get("/api/summary")
    def summary_agentcore() -> dict[str, Any]:
        try:
            return _agentcore_agent.daily_summary()
        except Exception as exc:  # noqa: BLE001
            log.warning("AgentCore summary failed, using local agent: %s", str(exc)[:200])
            out = _local_fallback(summary)
            out["agentcore_error"] = str(exc)[:200]
            return out


@app.get("/api/aws/status")
def aws_status() -> dict[str, Any]:
    return {
        "dynamo": dynamo_mirror.stats() if dynamo_mirror is not None else None,
        "agentcore": {"configured": True, "runtime_arn": _agentcore_agent.runtime_arn.rsplit(
            "/", 1)[-1]} if _agentcore_agent is not None else None,
    }
