from __future__ import annotations

import io
import json
import sys

import httpx
import respx
from conftest import API, CAM, PRESIGNED, history_event

from ringpartner import build_event, cli
from ringpartner.simulator import encode
from ringpartner.webhooks import sign

KEY = "k"


@respx.mock
def test_devices_table_never_prints_token(monkeypatch, capsys, devices_doc):
    monkeypatch.setenv("RING_ACCESS_TOKEN", "super-secret-token")
    respx.get(f"{API}/v1/devices").mock(return_value=httpx.Response(200, json=devices_doc))
    assert cli.main(["devices"]) == 0
    out = capsys.readouterr()
    assert "Front Door" in out.out and "encrypted" in out.out
    assert "super-secret-token" not in out.out + out.err


def test_missing_token(monkeypatch, capsys):
    monkeypatch.delenv("RING_ACCESS_TOKEN", raising=False)
    assert cli.main(["devices"]) == 2
    assert "RING_ACCESS_TOKEN" in capsys.readouterr().err


def test_verify_command(monkeypatch, capsys):
    body = encode(build_event("button_press", "dev1"))
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(body)))
    assert cli.main(["verify", "--key", KEY, "--signature", sign(KEY, body)]) == 0
    assert "button_press" in capsys.readouterr().out
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(body + b" ")))
    assert cli.main(["verify", "--key", KEY, "--signature", sign(KEY, body)]) == 1


@respx.mock
def test_simulate_command(capsys):
    route = respx.post("http://localhost:8000/hook").mock(return_value=httpx.Response(204))
    rc = cli.main(
        [
            "simulate",
            "motion_detected",
            "--device",
            "dev1",
            "--url",
            "http://localhost:8000/hook",
            "--key",
            KEY,
            "--sub-type",
            "human",
        ]
    )
    assert rc == 0
    req = route.calls.last.request
    assert req.headers["x-signature"] == sign(KEY, req.content)
    assert b'"sub_type":"human"' in req.content


@respx.mock
def test_capture_fixtures_tolerates_failures(tmp_path, monkeypatch, capsys, devices_doc):
    monkeypatch.setenv("RING_ACCESS_TOKEN", "t")
    respx.get(f"{API}/v1/devices").mock(return_value=httpx.Response(200, json=devices_doc))
    respx.route(host="api.amazonvision.com").mock(
        return_value=httpx.Response(403, json={"errors": [{"status": "403", "title": "Forbidden"}]})
    )
    assert cli.main(["capture-fixtures", "--dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "recorded 1 calls" in out and "FAILED" in out
    assert (tmp_path / "index.json").exists()


# -- snapshot: the default must work on the Developer Playground (review-04 finding #6) -------


def _mock_snapshot_route():
    post = respx.post(f"{API}/v1/devices/{CAM}/media/image/download").mock(
        return_value=httpx.Response(303, headers={"location": PRESIGNED})
    )
    respx.get(PRESIGNED).mock(
        return_value=httpx.Response(
            200, content=b"\xff\xd8jpeg", headers={"content-type": "image/jpeg"}
        )
    )
    return post


@respx.mock
def test_snapshot_default_uses_newest_history_event_start(tmp_path, monkeypatch, capsys):
    """No range request by default: the Playground answers latest_in_range with 403."""
    monkeypatch.setenv("RING_ACCESS_TOKEN", "t")
    respx.get(f"{API}/v1/history/devices/{CAM}/events").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    history_event("e2", "on_demand", 1_791_751_661_653),
                    history_event("e1", "on_demand", 1_791_751_603_045),
                ]
            },
        )
    )
    post = _mock_snapshot_route()
    out = tmp_path / "snap.jpg"
    assert cli.main(["snapshot", CAM, "--out", str(out)]) == 0
    body = json.loads(post.calls.last.request.content)
    assert body["type"] == "at_timestamp" and body["timestamp"] == 1_791_751_661_653
    assert "latest_in_range" not in json.dumps(body)
    assert out.read_bytes() == b"\xff\xd8jpeg"


@respx.mock
def test_snapshot_without_history_explains_instead_of_403(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("RING_ACCESS_TOKEN", "t")
    respx.get(f"{API}/v1/history/devices/{CAM}/events").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    post = _mock_snapshot_route()
    assert cli.main(["snapshot", CAM, "--out", str(tmp_path / "x.jpg")]) == 2
    assert "--at-ms" in capsys.readouterr().err
    assert not post.called


@respx.mock
def test_snapshot_latest_in_range_is_opt_in(tmp_path, monkeypatch):
    monkeypatch.setenv("RING_ACCESS_TOKEN", "t")
    post = _mock_snapshot_route()
    rc = cli.main(
        ["snapshot", CAM, "--out", str(tmp_path / "x.jpg"), "--latest-in-range", "--window", "5"]
    )
    assert rc == 0
    body = json.loads(post.calls.last.request.content)
    assert body["type"] == "latest_in_range"
    assert body["end_timestamp"] - body["start_timestamp"] == 5 * 60_000


@respx.mock
def test_snapshot_at_ms_skips_history(tmp_path, monkeypatch):
    monkeypatch.setenv("RING_ACCESS_TOKEN", "t")
    hist = respx.get(f"{API}/v1/history/devices/{CAM}/events")
    post = _mock_snapshot_route()
    assert cli.main(["snapshot", CAM, "--out", str(tmp_path / "x.jpg"), "--at-ms", "1234"]) == 0
    assert json.loads(post.calls.last.request.content)["timestamp"] == 1234
    assert not hist.called
