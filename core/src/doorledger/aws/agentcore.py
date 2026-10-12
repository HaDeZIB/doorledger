"""Client for the CareAgent deployed to Amazon Bedrock AgentCore Runtime.

The API keeps the ledger and the guardrails. For a family question it exports a read-only
snapshot (``snapshot.export_snapshot``) and calls ``InvokeAgentRuntime``; the runtime rebuilds
a sealed engine from the snapshot and runs the same Strands ``CareAgent`` with read-only tools
(see ``deploy/agentcore/app/CareAgent/main.py``).

Required permission for the caller: ``bedrock-agentcore:InvokeAgentRuntime`` on the runtime ARN.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .snapshot import export_snapshot

log = logging.getLogger("doorledger.aws.agentcore")

WARM_UP_INTERVAL_S = 300.0  # AgentCore keeps an idle session's microVM for ~15 min


def public_error(exc: BaseException) -> str:
    """Error text that is safe to send to a browser.

    botocore messages can quote ARNs and the AWS account id ("User: arn:aws:iam::<account>:...
    is not authorized"), so the client only ever gets a generic sentence plus the error code
    (e.g. ``AccessDeniedException``). The full message stays in the server log.
    """
    response = getattr(exc, "response", None)
    code = (response.get("Error") or {}).get("Code") if isinstance(response, dict) else None
    name = code if isinstance(code, str) and re.fullmatch(r"[A-Za-z]{1,64}", code) else (
        type(exc).__name__)
    return f"AgentCore runtime unavailable ({name})"


def session_id_for(engine: Any, now: datetime | None = None) -> str:
    """One runtime session per household per local day (>= 33 chars, as the API requires)."""
    now = now or engine.clock.now()
    day = now.astimezone(ZoneInfo(engine.household.patient.timezone)).date().isoformat()
    return f"doorledger-{engine.household.id}-{day}".ljust(33, "0")


class AgentCoreCareAgent:
    """Same surface as ``CareAgent.ask``/``daily_summary`` but returns API dicts."""

    def __init__(self, engine: Any, runtime_arn: str | None = None, *, client: Any = None,
                 region: str | None = None, qualifier: str = "DEFAULT") -> None:
        self.engine = engine
        self.runtime_arn = runtime_arn or os.environ["DOORLEDGER_AGENTCORE_ARN"]
        if client is None:
            import boto3
            from botocore.config import Config

            client = boto3.client(
                "bedrock-agentcore",
                region_name=region or self.runtime_arn.split(":")[3] or os.environ.get(
                    "AWS_REGION", "us-east-1"),
                config=Config(read_timeout=120, retries={"max_attempts": 2}))
        self.client = client
        self.qualifier = qualifier
        self._warm_lock = threading.Lock()
        self._warmed: dict[str, float] = {}  # session id -> monotonic time of the last ping

    def _call(self, payload: dict[str, Any]) -> Any:
        resp = self.client.invoke_agent_runtime(
            agentRuntimeArn=self.runtime_arn,
            runtimeSessionId=session_id_for(self.engine),
            payload=json.dumps(payload, ensure_ascii=False).encode(),
            qualifier=self.qualifier,
            contentType="application/json",
            accept="application/json",
        )
        body = resp["response"]
        raw = body.read() if hasattr(body, "read") else b"".join(body)
        return json.loads(raw.decode("utf-8"))

    def _invoke(self, payload: dict[str, Any], key: str) -> dict[str, Any]:
        t0 = time.perf_counter()
        data = self._call(payload)
        if not isinstance(data, dict) or key not in data:
            raise RuntimeError(f"unexpected AgentCore response: {str(data)[:200]}")
        data["runtime"] = "agentcore"
        data["roundtrip_ms"] = int((time.perf_counter() - t0) * 1000)
        return data

    def ask(self, question: str) -> dict[str, Any]:
        return self._invoke({"mode": "ask", "question": question.strip()[:500],
                             "snapshot": export_snapshot(self.engine)}, "answer")

    def daily_summary(self) -> dict[str, Any]:
        return self._invoke({"mode": "summary", "snapshot": export_snapshot(self.engine)},
                            "summary")

    # -- warm-up ---------------------------------------------------------------------------
    # The first InvokeAgentRuntime of a session boots its microVM: review 03 measured 7.6 s
    # round trip for a first answer whose handler took 2.3 s. A ping on the same session id
    # when a scenario starts moves that cold start off the first question. The ping never
    # reaches a model: the runtime answers ``{"mode": "ping"}`` directly (older deployed
    # builds reject the unknown mode with an error dict, which warms the session just the same).

    def ping(self) -> int:
        """Synchronous warm-up call; returns the round trip in ms."""
        t0 = time.perf_counter()
        self._call({"mode": "ping"})
        return int((time.perf_counter() - t0) * 1000)

    def warm_up(self, reason: str = "", *, min_interval: float = WARM_UP_INTERVAL_S,
                background: bool = True) -> threading.Thread | None:
        """Fire-and-forget ping, at most once per ``min_interval`` per runtime session.

        Never raises and never blocks the caller (the call runs on a daemon thread); a failed
        ping is logged and the next real question simply pays the cold start.
        """
        try:
            sid = session_id_for(self.engine)
        except Exception:  # noqa: BLE001 — a warm-up must never break its caller
            return None
        now = time.monotonic()
        with self._warm_lock:
            last = self._warmed.get(sid)
            if last is not None and now - last < min_interval:
                return None
            self._warmed[sid] = now

        def run() -> None:
            try:
                ms = self.ping()
                log.info("AgentCore warm-up (%s): %d ms", reason or "manual", ms)
            except Exception as exc:  # noqa: BLE001
                log.info("AgentCore warm-up (%s) failed: %s", reason or "manual", str(exc)[:200])
                with self._warm_lock:  # let the next trigger try again
                    self._warmed.pop(sid, None)

        if not background:
            run()
            return None
        t = threading.Thread(target=run, name="agentcore-warm-up", daemon=True)
        t.start()
        return t
