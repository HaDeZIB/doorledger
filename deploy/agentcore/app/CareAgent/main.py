"""DoorLedger CareAgent on Amazon Bedrock AgentCore Runtime.

Contract (POST /invocations, JSON):

    {"mode": "ask", "question": "Did Maria come today?", "snapshot": {...}}
    {"mode": "summary", "snapshot": {...}}
    {"mode": "ping"}            -> {"ok": true, ...}; warms the session's microVM, no model call

``snapshot`` is produced by ``doorledger.aws.snapshot.export_snapshot`` in the DoorLedger API.
The runtime rebuilds a sealed, in-memory engine from it and runs the same Strands
``CareAgent`` the API runs locally, with READ-ONLY tools (get_today_status, get_timeline,
export_evv). This runtime cannot message anyone:

* ``ask``/``daily_summary`` only receive read-only tools (``handle`` is never exposed here);
* the rebuilt engine's notifier raises on every send (``ReadOnlyNotifier``);
* contact details are stripped from the snapshot before it leaves the API;
* no notification credentials are configured in this runtime.

Guardrailed actions (notify, backup aide, pharmacy draft) stay in the DoorLedger API.

The ``doorledger`` package next to this file is a vendored copy made by
``deploy/agentcore/sync_core.py``; run it before ``agentcore dev`` / ``agentcore deploy``.
"""

from __future__ import annotations

import time

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from doorledger.agent import CareAgent
from doorledger.aws.snapshot import engine_from_snapshot

app = BedrockAgentCoreApp()
log = app.logger

MAX_QUESTION = 500


def _error(message: str) -> dict:
    return {"error": message, "runtime": "agentcore"}


@app.entrypoint
def invoke(payload, context=None):
    if not isinstance(payload, dict):
        return _error("payload must be a JSON object")
    mode = payload.get("mode", "ask")
    if mode == "ping":  # warm-up sent by the API when a demo scenario starts
        return {"ok": True, "runtime": "agentcore",
                "session_id": getattr(context, "session_id", None)}
    if mode not in ("ask", "summary"):
        return _error("mode must be 'ask' or 'summary' (this runtime cannot act)")
    question = payload.get("question", payload.get("prompt", ""))
    if mode == "ask" and (not isinstance(question, str) or not question.strip()):
        return _error("question must be a non-empty string")
    try:
        engine = engine_from_snapshot(payload.get("snapshot"))
    except (KeyError, TypeError, ValueError) as exc:
        return _error(f"invalid snapshot: {str(exc)[:200]}")

    t0 = time.perf_counter()
    agent = CareAgent(engine)
    if mode == "ask":
        reply, key = agent.ask(question[:MAX_QUESTION]), "answer"
    else:
        reply, key = agent.daily_summary(), "summary"
    out = reply.to_api(key)
    out.update({
        "runtime": "agentcore",
        "session_id": getattr(context, "session_id", None),
        "handler_ms": int((time.perf_counter() - t0) * 1000),
        "snapshot_now": engine.clock.now().isoformat(),
    })
    log.info("doorledger %s model=%s tools=%s latency_ms=%s", mode, reply.model,
             [c["name"] for c in reply.tool_calls], reply.latency_ms)
    return out


if __name__ == "__main__":
    app.run()
