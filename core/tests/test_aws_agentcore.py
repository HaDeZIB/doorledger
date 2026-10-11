"""AgentCore Runtime client + runtime entrypoint contract (no network).

The live test at the bottom invokes the deployed runtime and only runs with
DOORLEDGER_LIVE=1 and DOORLEDGER_AGENTCORE_ARN set.
"""

import io
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import boto3
import pytest
from botocore.response import StreamingBody
from botocore.stub import ANY, Stubber
from doorledger.agent import replay_scenario
from doorledger.aws.agentcore import AgentCoreCareAgent, session_id_for
from doorledger.clock import SimClock
from doorledger.domain import utcnow
from doorledger.engine import Engine
from doorledger.household import demo_household
from doorledger.ledger import Ledger
from doorledger.responder import Responder, TemplateWriter
from doorledger.weather import AmbientTemperature

TZ = ZoneInfo("America/Chicago")
DAY = datetime(2026, 10, 11, tzinfo=TZ)
ARN = "arn:aws:bedrock-agentcore:us-east-1:111122223333:runtime/DoorLedgerAgent_CareAgent-abc"


class Recorder:
    channel = "test"

    def send(self, person, message):
        return True


@pytest.fixture(scope="module")
def engine():
    hh = demo_household()
    eng = Engine(hh, Ledger(household=hh.id), Responder(hh, Recorder(), TemplateWriter()),
                 SimClock(utcnow(), 0.0), AmbientTemperature(hh.lat, hh.lon, override_c=-9.0))
    replay_scenario(eng, "full_day", DAY)
    return eng


def _body(obj):
    raw = json.dumps(obj).encode()
    return StreamingBody(io.BytesIO(raw), len(raw))


def test_session_id_is_per_household_day_and_long_enough(engine):
    sid = session_id_for(engine)
    assert sid.startswith("doorledger-hh_rosa-2026-10-11") and len(sid) >= 33


def test_ask_sends_snapshot_and_parses_reply(engine):
    c = boto3.client("bedrock-agentcore", region_name="us-east-1", aws_access_key_id="x",
                     aws_secret_access_key="x")
    with Stubber(c) as stub:
        stub.add_response(
            "invoke_agent_runtime",
            {"response": _body({"answer": "Maria arrived at 09:22.", "model": "m",
                                "tool_calls": [{"name": "get_today_status", "input": {}}],
                                "latency_ms": 900, "usage": {}}),
             "contentType": "application/json", "statusCode": 200},
            {"agentRuntimeArn": ARN, "runtimeSessionId": session_id_for(engine),
             "payload": ANY, "qualifier": "DEFAULT", "contentType": "application/json",
             "accept": "application/json"})
        out = AgentCoreCareAgent(engine, ARN, client=c).ask("Did Maria come today?")
    assert out["answer"].startswith("Maria") and out["runtime"] == "agentcore"
    assert "roundtrip_ms" in out


def test_bad_reply_raises(engine):
    c = boto3.client("bedrock-agentcore", region_name="us-east-1", aws_access_key_id="x",
                     aws_secret_access_key="x")
    with Stubber(c) as stub:
        stub.add_response("invoke_agent_runtime",
                          {"response": _body({"error": "boom"}), "statusCode": 200,
                           "contentType": "application/json"})
        with pytest.raises(RuntimeError):
            AgentCoreCareAgent(engine, ARN, client=c).daily_summary()


@pytest.mark.skipif(not (os.environ.get("DOORLEDGER_LIVE") == "1"
                         and os.environ.get("DOORLEDGER_AGENTCORE_ARN")),
                    reason="live AgentCore test: set DOORLEDGER_LIVE=1 and DOORLEDGER_AGENTCORE_ARN")
def test_live_agentcore_ask(engine):
    out = AgentCoreCareAgent(engine).ask("Did Maria come today, and how long did she stay?")
    assert "09:22" in out["answer"] or "9:22" in out["answer"]
    assert {c["name"] for c in out["tool_calls"]} & {"get_today_status", "get_timeline"}


def test_api_hook_swaps_routes_only_when_flag_set():
    """Import the API in a clean interpreter with the flag set (no network at import)."""
    import subprocess
    import sys

    code = ("from doorledger import api; from fastapi.routing import APIRoute; "
            "print(sorted(r.endpoint.__name__ for r in api.app.router.routes "
            "if isinstance(r, APIRoute) and r.path in ('/api/ask', '/api/summary')))")
    base = {**os.environ, "DOORLEDGER_PERCEPTION": "off", "DOORLEDGER_WRITER": "template",
            "AWS_ACCESS_KEY_ID": "x", "AWS_SECRET_ACCESS_KEY": "x"}
    base.pop("DOORLEDGER_AGENTCORE_ARN", None)
    base.pop("DOORLEDGER_DYNAMO", None)
    on = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=False,
                        env={**base, "DOORLEDGER_AGENTCORE_ARN": ARN})
    off = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False,
                         timeout=60, env=base)
    assert on.returncode == 0, on.stderr[-500:]
    assert on.stdout.strip().splitlines()[-1] == "['ask_agentcore', 'summary_agentcore']"
    assert off.stdout.strip().splitlines()[-1] == "['ask', 'summary']"
