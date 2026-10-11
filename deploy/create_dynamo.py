#!/usr/bin/env python3
"""Create (or verify) the DynamoDB table that mirrors the DoorLedger ledger. Idempotent.

    uv run python deploy/create_dynamo.py            # create if missing, enable TTL, tag
    uv run python deploy/create_dynamo.py --check    # only report, change nothing
    uv run python deploy/create_dynamo.py --smoke    # also write+read+delete one test item

Table: pk (S, HASH) = household, sk (S, RANGE) = "<at>#<id>", PAY_PER_REQUEST (no idle
cost), TTL on ``expires_at``, tags Project=doorledger. See core/src/doorledger/aws/dynamo.py.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime

import boto3
from botocore.exceptions import ClientError

TAGS = [{"Key": "Project", "Value": "doorledger"}, {"Key": "Component", "Value": "ledger-mirror"}]
TTL_ATTRIBUTE = "expires_at"


def describe(ddb, table: str) -> dict | None:
    try:
        return ddb.describe_table(TableName=table)["Table"]
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ResourceNotFoundException":
            return None
        raise


def ensure_table(ddb, table: str, check: bool) -> dict:
    desc = describe(ddb, table)
    if desc is None:
        if check:
            sys.exit(f"table {table} does not exist")
        print(f"creating {table} (PAY_PER_REQUEST)...")
        ddb.create_table(
            TableName=table,
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"},
                                  {"AttributeName": "sk", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"},
                       {"AttributeName": "sk", "KeyType": "RANGE"}],
            BillingMode="PAY_PER_REQUEST",
            Tags=TAGS,
        )
        ddb.get_waiter("table_exists").wait(TableName=table,
                                            WaiterConfig={"Delay": 2, "MaxAttempts": 60})
        desc = describe(ddb, table)
    else:
        print(f"{table} exists ({desc['TableStatus']})")
        keys = {k["AttributeName"]: k["KeyType"] for k in desc["KeySchema"]}
        if keys != {"pk": "HASH", "sk": "RANGE"}:
            sys.exit(f"{table} has an unexpected key schema {keys}; refusing to touch it")
        if not check:
            tags = {t["Key"]: t["Value"] for t in
                    ddb.list_tags_of_resource(ResourceArn=desc["TableArn"]).get("Tags", [])}
            if tags.get("Project") != "doorledger":
                ddb.tag_resource(ResourceArn=desc["TableArn"], Tags=TAGS)
                print("  tagged Project=doorledger")
    return desc


def ensure_ttl(ddb, table: str, check: bool) -> str:
    ttl = ddb.describe_time_to_live(TableName=table)["TimeToLiveDescription"]
    status = ttl.get("TimeToLiveStatus", "DISABLED")
    if status in ("ENABLED", "ENABLING"):
        return f"{status} on {ttl.get('AttributeName')}"
    if check:
        return status
    for attempt in range(10):  # TTL can't be set while the table is still settling
        try:
            ddb.update_time_to_live(TableName=table, TimeToLiveSpecification={
                "Enabled": True, "AttributeName": TTL_ATTRIBUTE})
            return f"ENABLING on {TTL_ATTRIBUTE}"
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ResourceInUseException" or attempt == 9:
                raise
            time.sleep(3)
    return status


def smoke(table: str, region: str) -> None:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "core", "src"))
    from doorledger.aws.dynamo import DynamoMirror

    m = DynamoMirror("hh_smoketest", table, region=region, background=False, ttl_days=1)
    now = datetime.now(UTC).isoformat()
    rec = {"id": "obs_smoke", "kind": "observation", "subtype": "person_at_door", "at": now,
           "ref": None, "body": {"source": "simulated", "note": "create_dynamo.py --smoke"}}
    t0 = time.perf_counter()
    m(rec)
    put_ms = (time.perf_counter() - t0) * 1000
    got = m.query()
    assert got and got[-1]["id"] == "obs_smoke", got
    m.client.delete_item(TableName=table, Key={"pk": {"S": "hh_smoketest"},
                                               "sk": {"S": f"{now}#obs_smoke"}})
    print(f"smoke ok: put {put_ms:.0f} ms, query returned {len(got)} item(s), cleaned up")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--table", default=os.environ.get("DOORLEDGER_DYNAMO_TABLE",
                                                      "doorledger-ledger"))
    ap.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    ap.add_argument("--check", action="store_true", help="report only; change nothing")
    ap.add_argument("--smoke", action="store_true", help="write/read/delete one test item")
    args = ap.parse_args()
    ddb = boto3.client("dynamodb", region_name=args.region)
    desc = ensure_table(ddb, args.table, args.check)
    ttl = ensure_ttl(ddb, args.table, args.check)
    acct = desc["TableArn"].split(":")[4]
    print(json.dumps({
        "table": args.table,
        "arn": desc["TableArn"].replace(acct, "<account-id>"),
        "status": desc["TableStatus"],
        "billing": desc.get("BillingModeSummary", {}).get("BillingMode", "PROVISIONED"),
        "ttl": ttl,
    }, indent=2))
    if args.smoke:
        smoke(args.table, args.region)


if __name__ == "__main__":
    main()
