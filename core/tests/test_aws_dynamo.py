"""DynamoDB ledger mirror, with botocore's Stubber (no network, no credentials)."""

import json
from datetime import UTC, datetime, timedelta

import boto3
import pytest
from botocore.stub import ANY, Stubber
from doorledger.aws.dynamo import DynamoMirror, attach_mirror, from_item, to_item
from doorledger.domain import (
    Action,
    Finding,
    FindingKind,
    Observation,
    ObservationKind,
    Severity,
    Source,
)
from doorledger.ledger import Ledger

T0 = datetime(2026, 10, 11, 19, 7, tzinfo=UTC)


@pytest.fixture
def client():
    c = boto3.client("dynamodb", region_name="us-east-1", aws_access_key_id="x",
                     aws_secret_access_key="x")
    with Stubber(c) as stub:
        c.stub = stub
        yield c


def test_item_shape_and_ttl():
    rec = {"id": "fnd_1", "kind": "finding", "subtype": "package_at_risk", "at": T0.isoformat(),
           "ref": "exp_1", "body": {"severity": "warning", "minutes": 20.5, "summary": "x"}}
    item = to_item("hh_rosa", rec, ttl_days=30)
    assert item["pk"] == {"S": "hh_rosa"}
    assert item["sk"] == {"S": f"{T0.isoformat()}#fnd_1"}
    assert item["severity"] == {"S": "warning"} and item["ref"] == {"S": "exp_1"}
    assert int(item["expires_at"]["N"]) == int((T0 + timedelta(days=30)).timestamp())
    assert json.loads(item["body"]["S"])["minutes"] == 20.5  # floats survive (no Decimal)
    assert from_item(item) == rec


def test_every_record_kind_is_mirrored(client):
    ledger = Ledger(household="hh_rosa")
    mirror = attach_mirror(ledger, client=client, background=False)
    for _ in range(3):
        client.stub.add_response("put_item", {}, {"TableName": "doorledger-ledger", "Item": ANY})
    o = Observation(ObservationKind.PACKAGE_DROPPED, T0, Source.RING_LIVE, id="obs_1")
    f = Finding(FindingKind.PACKAGE_AT_RISK, Severity.WARNING, T0, "at risk", "exp_1", id="fnd_1")
    a = Action("notify", "Luis (neighbor)", "please bring it in", T0, "fnd_1", id="act_1")
    ledger.add_observation(o, "exp_1")
    ledger.add_finding(f)
    ledger.add_action(a, "exp_1")
    client.stub.assert_no_pending_responses()
    assert mirror.stats()["written"] == 3 and mirror.stats()["failed"] == 0


def test_put_failure_never_breaks_the_ledger(client):
    ledger = Ledger(household="hh_rosa")
    mirror = attach_mirror(ledger, client=client, background=False)
    client.stub.add_client_error("put_item", "ProvisionedThroughputExceededException")
    ledger.add_observation(Observation(ObservationKind.PERSON_AT_DOOR, T0, Source.SIMULATED))
    assert len(ledger.records()) == 1
    assert mirror.failed == 1 and "ProvisionedThroughput" in mirror.last_error


def test_background_writer_flushes(client):
    mirror = DynamoMirror("hh_rosa", client=client, background=True)
    for _ in range(5):
        client.stub.add_response("put_item", {})
    for i in range(5):
        mirror({"id": f"obs_{i}", "kind": "observation", "subtype": "person_at_door",
                "at": T0.isoformat(), "ref": None, "body": {}})
    assert mirror.flush(5)
    mirror.close()
    assert mirror.written == 5


def test_query_round_trip(client):
    rec = {"id": "obs_1", "kind": "observation", "subtype": "package_dropped",
           "at": T0.isoformat(), "ref": None, "body": {"source": "ring_live_view"}}
    client.stub.add_response(
        "query", {"Items": [to_item("hh_rosa", rec)]},
        {"TableName": "doorledger-ledger", "KeyConditionExpression": "pk = :pk",
         "ExpressionAttributeValues": {":pk": {"S": "hh_rosa"}}, "Limit": 500})
    mirror = DynamoMirror("hh_rosa", client=client, background=False)
    assert mirror.query() == [rec]
