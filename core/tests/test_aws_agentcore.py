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


# -- warm-up ------------------------------------------------------------------------------


class FakeRuntime:
    """Stands in for the bedrock-agentcore client (no network)."""

    def __init__(self, *, fail: Exception | None = None, delay: float = 0.0):
        self.calls: list[dict] = []
        self.fail, self.delay = fail, delay

    def invoke_agent_runtime(self, **kw):
        import time

        self.calls.append(kw)
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise self.fail
        return {"response": _body({"ok": True, "runtime": "agentcore"})}


def test_warm_up_pings_the_same_session_once_per_interval(engine):
    rt = FakeRuntime()
    agent = AgentCoreCareAgent(engine, ARN, client=rt)
    agent.warm_up("scenario:full_day", background=False)
    agent.warm_up("scenario:porch_cold", background=False)  # debounced
    assert len(rt.calls) == 1
    call = rt.calls[0]
    assert json.loads(call["payload"]) == {"mode": "ping"}  # no snapshot, no question, no model
    assert call["runtimeSessionId"] == session_id_for(engine)  # same microVM as later asks
    agent.warm_up("again", background=False, min_interval=0)
    assert len(rt.calls) == 2


def test_warm_up_never_blocks_or_raises(engine):
    import time

    from botocore.exceptions import ClientError

    err = ClientError({"Error": {"Code": "AccessDeniedException", "Message": "denied"}},
                      "InvokeAgentRuntime")
    rt = FakeRuntime(fail=err, delay=0.5)
    agent = AgentCoreCareAgent(engine, ARN, client=rt)
    t0 = time.perf_counter()
    thread = agent.warm_up("scenario:full_day")
    assert time.perf_counter() - t0 < 0.2  # the caller (a scenario start) is not held up
    thread.join(5)
    assert len(rt.calls) == 1
    # a failed ping does not count as warm: the next trigger tries again
    agent.warm_up("retry", background=False)
    assert len(rt.calls) == 2


# -- error text sent to the browser ---------------------------------------------------------

LEAKY = ("User: arn:aws:iam::111122223333:user/doorledger-dev is not authorized to perform: "
         "bedrock-agentcore:InvokeAgentRuntime on resource: " + ARN)


def _no_aws_identifiers(text: str) -> None:
    import re

    assert "arn:" not in text
    assert not re.search(r"\d{12}", text), text


def test_public_error_never_contains_arns_or_account_ids():
    from botocore.exceptions import ClientError
    from doorledger.aws.agentcore import public_error

    exc = ClientError({"Error": {"Code": "AccessDeniedException", "Message": LEAKY}},
                      "InvokeAgentRuntime")
    assert LEAKY in str(exc)  # botocore really does put it in the message
    msg = public_error(exc)
    assert msg == "AgentCore runtime unavailable (AccessDeniedException)"
    _no_aws_identifiers(msg)
    _no_aws_identifiers(public_error(RuntimeError(LEAKY)))


def test_api_responses_never_leak_agentcore_error_text():
    """Regression (review 03 §3.6): /api/ask and /api/summary used to echo the raw exception."""
    import subprocess
    import sys

    code = f"""
import json
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient
from doorledger import api

LEAKY = {LEAKY!r}

class Rt:
    pings = 0
    def invoke_agent_runtime(self, **kw):
        if json.loads(kw["payload"]) == {{"mode": "ping"}}:
            Rt.pings += 1
        raise ClientError({{"Error": {{"Code": "AccessDeniedException", "Message": LEAKY}}}},
                          "InvokeAgentRuntime")

class Reply:
    def to_api(self, key):
        return {{key: "Maria arrived at 09:22.", "tool_calls": [], "model": "stub",
                 "latency_ms": 1, "usage": None}}

class OkAgent:
    def ask(self, q): return Reply()
    def daily_summary(self): return Reply()

class DeniedAgent:
    def ask(self, q): raise RuntimeError("no Bedrock model available for the agent: " + LEAKY)
    daily_summary = lambda self: self.ask("")

api._agentcore_agent.client = Rt()
c = TestClient(api.app)  # no startup events: nothing reaches AWS
out = {{}}
api._agent = lambda: OkAgent()
out["ask_fallback"] = c.post("/api/ask", json={{"question": "Did Maria come?"}}).json()
out["summary_fallback"] = c.get("/api/summary").json()
api._agent = lambda: DeniedAgent()
r = c.post("/api/ask", json={{"question": "Did Maria come?"}})
out["ask_503"] = [r.status_code, r.text]
r = c.get("/api/summary")
out["summary_503"] = [r.status_code, r.text]
r = c.post("/api/demo/run", json={{"scenario": "porch_cold", "speed": 60}})
out["demo_run"] = [r.status_code, r.json()]
import time
for _ in range(50):
    if Rt.pings:
        break
    time.sleep(0.05)
out["pings"] = Rt.pings
print(json.dumps(out))
"""
    env = {**os.environ, "DOORLEDGER_PERCEPTION": "off", "DOORLEDGER_WRITER": "template",
           "AWS_ACCESS_KEY_ID": "x", "AWS_SECRET_ACCESS_KEY": "x",
           "DOORLEDGER_AGENTCORE_ARN": ARN, "DOORLEDGER_DB": ":memory:"}
    env.pop("DOORLEDGER_DYNAMO", None)
    env.pop("TELEGRAM_BOT_TOKEN", None)
    env.pop("DOORLEDGER_SMS_TO", None)
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          timeout=90, check=False, env=env)
    assert proc.returncode == 0, proc.stderr[-1500:]
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    for key in ("ask_fallback", "summary_fallback"):
        assert out[key]["runtime"] == "local"
        assert out[key]["agentcore_error"] == "AgentCore runtime unavailable (AccessDeniedException)"
    assert out["ask_503"][0] == 503 and out["summary_503"][0] == 503
    _no_aws_identifiers(proc.stdout)
    # a scenario start fires the warm-up in the background and still succeeds when it fails
    assert out["demo_run"] == [200, {"ok": True, "scenario": "porch_cold"}]
    assert out["pings"] == 1
