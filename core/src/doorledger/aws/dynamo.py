"""DynamoDB mirror of the append-only care ledger.

SQLite stays the system of record for the running process (fast, transactional, used by the
rules). Every record the ledger writes (expectation, observation, finding, action) is also put
into a DynamoDB table so the care history survives the process, can be queried per household
and day, and expires automatically after the retention window.

Table ``doorledger-ledger`` (created by ``deploy/create_dynamo.py``, PAY_PER_REQUEST):

    pk   (S, HASH)   household id                      "hh_rosa"
    sk   (S, RANGE)  "<at, UTC ISO-8601>#<record id>"  "2026-10-11T19:07:00+00:00#obs_ab12"
                     (normalised to UTC so string order == time order across offsets)
    kind, subtype, at, id, ref        top-level strings for filters
    severity / target                 findings / actions only
    body                              the record body as JSON text (no Decimal conversion)
    expires_at (N)                    TTL, epoch seconds = at + retention days

Writes happen on a background thread so a slow network never blocks the rules engine; a
failed put is logged and counted, never raised into the ledger.

Enable in the API with ``DOORLEDGER_DYNAMO=1`` (optional ``DOORLEDGER_DYNAMO_TABLE``,
``DOORLEDGER_DYNAMO_TTL_DAYS``, ``AWS_REGION``).
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

log = logging.getLogger("doorledger.aws.dynamo")

DEFAULT_TABLE = "doorledger-ledger"
DEFAULT_TTL_DAYS = 30
TTL_ATTRIBUTE = "expires_at"
_STOP = object()


def _utc(at: datetime) -> str:
    return at.astimezone(UTC).isoformat() if at.tzinfo else at.isoformat()


def to_item(household: str, record: dict[str, Any], ttl_days: int = DEFAULT_TTL_DAYS
            ) -> dict[str, dict[str, str]]:
    """Ledger record -> DynamoDB low-level item (attribute-value maps)."""
    at = datetime.fromisoformat(record["at"])
    body = record.get("body") or {}
    item: dict[str, dict[str, str]] = {
        "pk": {"S": household},
        "sk": {"S": f"{_utc(at)}#{record['id']}"},
        "id": {"S": record["id"]},
        "kind": {"S": record["kind"]},
        "subtype": {"S": str(record["subtype"])},
        "at": {"S": record["at"]},
        "body": {"S": json.dumps(body, ensure_ascii=False, default=str)},
        TTL_ATTRIBUTE: {"N": str(int((at + timedelta(days=ttl_days)).timestamp()))},
    }
    if record.get("ref"):
        item["ref"] = {"S": record["ref"]}
    if record["kind"] == "finding" and body.get("severity"):
        item["severity"] = {"S": str(body["severity"])}
    if record["kind"] == "action" and body.get("target"):
        item["target"] = {"S": str(body["target"])}
    return item


def from_item(item: dict[str, dict[str, str]]) -> dict[str, Any]:
    """DynamoDB item -> the same record dict the SQLite ledger returns."""
    return {"id": item["id"]["S"], "kind": item["kind"]["S"], "subtype": item["subtype"]["S"],
            "at": item["at"]["S"], "ref": item.get("ref", {}).get("S"),
            "body": json.loads(item["body"]["S"])}


class DynamoMirror:
    """Ledger listener: ``ledger.subscribe(DynamoMirror(...))``.

    ``background=False`` writes inline (used by tests and one-off scripts).
    """

    def __init__(self, household: str, table: str | None = None, *, client: Any = None,
                 region: str | None = None, ttl_days: int | None = None,
                 background: bool = True, max_queue: int = 10_000) -> None:
        self.household = household
        self.table = table or os.environ.get("DOORLEDGER_DYNAMO_TABLE", DEFAULT_TABLE)
        self.ttl_days = ttl_days or int(os.environ.get("DOORLEDGER_DYNAMO_TTL_DAYS",
                                                       DEFAULT_TTL_DAYS))
        if client is None:
            import boto3

            client = boto3.client("dynamodb", region_name=region or os.environ.get(
                "AWS_REGION", "us-east-1"))
        self.client = client
        self.written = 0
        self.failed = 0
        self.dropped = 0
        self.last_error: str | None = None
        self._q: queue.Queue | None = None
        self._thread: threading.Thread | None = None
        if background:
            self._q = queue.Queue(maxsize=max_queue)
            self._thread = threading.Thread(target=self._drain, name="doorledger-dynamo",
                                            daemon=True)
            self._thread.start()

    # Ledger listener protocol: callback(record_dict)
    def __call__(self, record: dict[str, Any]) -> None:
        if self._q is None:
            self._write(record)
            return
        try:
            self._q.put_nowait(record)
        except queue.Full:
            self.dropped += 1
            log.warning("dynamo mirror queue full; dropped %s", record.get("id"))

    def _write(self, record: dict[str, Any]) -> None:
        try:
            self.client.put_item(TableName=self.table,
                                 Item=to_item(self.household, record, self.ttl_days))
            self.written += 1
        except Exception as exc:  # noqa: BLE001 — mirror failures never break the ledger
            self.failed += 1
            self.last_error = str(exc)[:300]
            log.warning("dynamo mirror put failed for %s: %s", record.get("id"), self.last_error)

    def _drain(self) -> None:
        assert self._q is not None
        while True:
            rec = self._q.get()
            try:
                if rec is _STOP:
                    return
                self._write(rec)
            finally:
                self._q.task_done()

    def flush(self, timeout: float = 10.0) -> bool:
        """Block until queued records are written (True) or ``timeout`` passes (False)."""
        if self._q is None:
            return True
        done = threading.Event()

        def waiter() -> None:
            self._q.join()  # type: ignore[union-attr]
            done.set()

        threading.Thread(target=waiter, daemon=True).start()
        return done.wait(timeout)

    def close(self, timeout: float = 10.0) -> None:
        if self._q is not None and self._thread is not None and self._thread.is_alive():
            self.flush(timeout)
            self._q.put(_STOP)
            self._thread.join(timeout)

    def stats(self) -> dict[str, Any]:
        return {"table": self.table, "written": self.written, "failed": self.failed,
                "dropped": self.dropped, "pending": self._q.qsize() if self._q else 0,
                "last_error": self.last_error}

    # -- reads (for scripts / a future multi-instance API) ----------------------------

    def query(self, since: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        """Records for this household in time order, optionally from an ISO timestamp."""
        if since:
            since = _utc(datetime.fromisoformat(since))
        kwargs: dict[str, Any] = {
            "TableName": self.table,
            "KeyConditionExpression": "pk = :pk" + (" AND sk >= :since" if since else ""),
            "ExpressionAttributeValues": {":pk": {"S": self.household},
                                          **({":since": {"S": since}} if since else {})},
            "Limit": limit,
        }
        resp = self.client.query(**kwargs)
        return [from_item(i) for i in resp.get("Items", [])]


def attach_mirror(ledger: Any, **kwargs: Any) -> DynamoMirror:
    """Subscribe a mirror to ``ledger`` (uses ``ledger.household`` as the partition key)."""
    mirror = DynamoMirror(ledger.household, **kwargs)
    ledger.subscribe(mirror)
    log.info("dynamo mirror on: table=%s household=%s", mirror.table, mirror.household)
    return mirror
