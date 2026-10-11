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
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .snapshot import export_snapshot

log = logging.getLogger("doorledger.aws.agentcore")


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

    def _invoke(self, payload: dict[str, Any], key: str) -> dict[str, Any]:
        t0 = time.perf_counter()
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
        data = json.loads(raw.decode("utf-8"))
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
