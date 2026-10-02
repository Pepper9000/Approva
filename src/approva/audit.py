"""Append and verify the tamper-evident audit event chain."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from approva import db
from approva.schemas import TraceEvent

GENESIS = "0" * 64


def _canonical(value: object) -> str:
    """Serialize values in the canonical audit representation."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def compute_hash(prev_hash: str, body_json: str) -> str:
    """Hash a previous digest and the exact canonical event body string."""
    return hashlib.sha256((prev_hash + body_json).encode("utf-8")).hexdigest()


def append(event: TraceEvent, db_path=None) -> TraceEvent:
    """Persist and hash an event, returning it with its assigned sequence."""
    db.init_db(db_path)
    body = event.model_dump(mode="json", exclude={"seq"})
    body_json = _canonical(body)
    with db.connection(db_path) as conn:
        previous = conn.execute("SELECT hash FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
        prev_hash = previous[0] if previous else GENESIS
        digest = compute_hash(prev_hash, body_json)
        cursor = conn.execute(
            "INSERT INTO audit_events(request_id,ts,agent,step,status,summary,detail_json,"
            "latency_ms,tokens_in,tokens_out,prev_hash,hash,body_json) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                body["request_id"], body["ts"], body["agent"], body["step"],
                body["status"], body["summary"], _canonical(body["detail"]),
                body["latency_ms"], body["tokens_in"], body["tokens_out"],
                prev_hash, digest, body_json,
            ),
        )
        sequence = cursor.lastrowid
    return event.model_copy(update={"seq": sequence})


def verify_chain(db_path=None) -> tuple[bool, int | None]:
    """Verify hashes against the stored canonical bodies in sequence order."""
    db.init_db(db_path)
    previous = GENESIS
    with db.connection(db_path) as conn:
        rows = conn.execute(
            "SELECT seq,prev_hash,hash,body_json FROM audit_events ORDER BY seq"
        ).fetchall()
    for row in rows:
        if row["prev_hash"] != previous or compute_hash(previous, row["body_json"]) != row["hash"]:
            return False, row["seq"]
        previous = row["hash"]
    return True, None


def tamper(seq: int, db_path=None) -> bool:
    """Alter a stored body for development demos and tamper-detection tests."""
    with db.connection(db_path) as conn:
        row = conn.execute("SELECT body_json FROM audit_events WHERE seq=?", (seq,)).fetchone()
        if row is None:
            return False
        body = json.loads(row["body_json"])
        body["summary"] = f"{body.get('summary', '')} (tampered)"
        conn.execute("UPDATE audit_events SET body_json=? WHERE seq=?", (_canonical(body), seq))
    return True