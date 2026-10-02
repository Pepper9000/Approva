from datetime import datetime, timezone

import pytest

from approva import audit, db
from approva.schemas import TraceEvent


def event(number: int) -> TraceEvent:
    """Build a deterministic audit event for chain tests."""
    return TraceEvent(
        request_id="REQ-0001",
        ts=datetime(2026, 10, 2, 12, 0, number, tzinfo=timezone.utc),
        agent="orchestrator",
        step=f"step-{number}",
        status="ok",
        summary=f"event {number}",
    )


def test_chain_verifies_and_stores_hashed_body(tmp_path):
    path = tmp_path / "audit.db"
    db.init_db(path)
    stored = audit.append(event(1), path)
    assert stored.seq == 1
    assert audit.verify_chain(path) == (True, None)
    with db.connection(path) as conn:
        row = conn.execute("SELECT body_json,hash,prev_hash FROM audit_events").fetchone()
    assert audit.compute_hash(row["prev_hash"], row["body_json"]) == row["hash"]


@pytest.mark.parametrize("bad_sequence", [1, 2, 3])
def test_tampering_any_row_reports_first_broken_sequence(tmp_path, bad_sequence):
    path = tmp_path / f"audit-{bad_sequence}.db"
    db.init_db(path)
    for index in range(1, 4):
        audit.append(event(index), path)
    assert audit.tamper(bad_sequence, path)
    assert audit.verify_chain(path) == (False, bad_sequence)