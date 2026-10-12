"""Append-only care ledger (SQLite locally; DynamoDB adapter can mirror the same records).

Every expectation, observation, finding and action is stored as JSON with a timestamp, so
the dashboard timeline, the EVV export and the family summary all read from one source.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .domain import Action, Expectation, Finding, Observation

_SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    id TEXT PRIMARY KEY,
    household TEXT NOT NULL,
    kind TEXT NOT NULL,         -- expectation | observation | finding | action | ring_event
    subtype TEXT NOT NULL,
    at TEXT NOT NULL,
    ref TEXT,                   -- expectation id this record relates to
    body TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_records_household_at ON records(household, at);
CREATE INDEX IF NOT EXISTS idx_records_ref ON records(ref);
"""


class Ledger:
    def __init__(self, path: str | Path = ":memory:", household: str = "default") -> None:
        self.household = household
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_SCHEMA)
        self._listeners: list[Any] = []

    def subscribe(self, callback: Any) -> None:
        """callback(record_dict) is called after every write (used for SSE to the dashboard)."""
        self._listeners.append(callback)

    def _put(self, kind: str, subtype: str, rid: str, at: datetime, ref: str | None,
             body: dict[str, Any]) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO records VALUES (?,?,?,?,?,?,?)",
                (rid, self.household, kind, subtype, at.isoformat(), ref, json.dumps(body)),
            )
            self._db.commit()
        record = {"id": rid, "kind": kind, "subtype": subtype, "at": at.isoformat(), "ref": ref,
                  "body": body}
        for cb in list(self._listeners):
            try:
                cb(record)
            except Exception:  # noqa: BLE001 — a broken listener must not break the ledger
                pass

    def add_expectation(self, e: Expectation) -> None:
        self._put("expectation", e.kind, e.id, e.window_start, e.id, e.to_dict())

    def add_observation(self, o: Observation, ref: str | None = None) -> None:
        self._put("observation", o.kind, o.id, o.at, ref, o.to_dict())

    def add_finding(self, f: Finding) -> None:
        self._put("finding", f.kind, f.id, f.at, f.expectation_id, f.to_dict())

    def add_action(self, a: Action, ref: str | None = None) -> None:
        self._put("action", a.kind, a.id, a.at, ref, a.to_dict())

    def update_action(self, a: Action) -> None:
        """Rewrite an action's body in place (a call's outcome arrives after it was placed).
        Keeps its time and ref; listeners get the updated record. No-op if it isn't stored yet
        (the caller mutated the Action, so the first write will carry the update)."""
        with self._lock:
            row = self._db.execute("SELECT at, ref FROM records WHERE id = ? AND household = ?",
                                   (a.id, self.household)).fetchone()
        if row is not None:
            self._put("action", a.kind, a.id, datetime.fromisoformat(row["at"]), row["ref"],
                      a.to_dict())

    def add_ring_event(self, body: dict[str, Any], at: datetime) -> None:
        """A Ring history row the live poller acted on (``ding``, ``on_demand``, ``motion``)."""
        self._put("ring_event", str(body.get("event_type", "unknown")), f"ring_{body['id']}", at,
                  None, body)

    def records(self, kinds: Iterable[str] | None = None, since: datetime | None = None,
                ref: str | None = None) -> list[dict[str, Any]]:
        q = "SELECT * FROM records WHERE household = ?"
        args: list[Any] = [self.household]
        if kinds:
            kinds = list(kinds)
            q += f" AND kind IN ({','.join('?' * len(kinds))})"
            args += kinds
        if since:
            q += " AND at >= ?"
            args.append(since.isoformat())
        if ref:
            q += " AND ref = ?"
            args.append(ref)
        q += " ORDER BY at ASC"
        with self._lock:
            rows = self._db.execute(q, args).fetchall()
        return [
            {"id": r["id"], "kind": r["kind"], "subtype": r["subtype"], "at": r["at"],
             "ref": r["ref"], "body": json.loads(r["body"])}
            for r in rows
        ]

    def has_finding(self, expectation_id: str | None, kind: str) -> bool:
        with self._lock:
            row = self._db.execute(
                "SELECT 1 FROM records WHERE household=? AND kind='finding' AND subtype=? AND "
                "IFNULL(ref,'')=IFNULL(?, '') LIMIT 1",
                (self.household, kind, expectation_id),
            ).fetchone()
        return row is not None
