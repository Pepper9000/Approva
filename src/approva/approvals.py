"""Multi-role human approval service."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Iterator

from approva import audit, db
from approva.orchestrator import resume_after_approval
from approva.schemas import RequestStatus, Role, TraceEvent


def _event(request_id: str, step: str, status: str, summary: str, detail: dict) -> TraceEvent:
    """Append an approval event to the audit chain."""
    return audit.append(TraceEvent(
        request_id=request_id, ts=datetime.now(timezone.utc), agent="approval",
        step=step, status=status, summary=summary, detail=detail,
    ))


def _identity(approver_id: str, required_role: Role, requester_id: str) -> bool:
    """Check that the approver holds the requested role for this request."""
    with db.connection() as conn:
        approver = conn.execute("SELECT role,manager_id FROM employees WHERE id=?", (approver_id,)).fetchone()
        requester = conn.execute("SELECT manager_id FROM employees WHERE id=?", (requester_id,)).fetchone()
    if not approver or not requester:
        return False
    if required_role == Role.MANAGER:
        return requester["manager_id"] == approver_id and approver["role"] == "manager"
    return approver["role"] == required_role.value


def submit(
    request_id: str,
    approver_id: str,
    role: Role | str,
    verdict: str,
    comment: str | None = None,
) -> Iterator[TraceEvent]:
    """Validate, record, and apply one human approval decision."""
    request = db.get_request(request_id)
    if not request:
        raise ValueError(f"Request not found: {request_id}")
    if request["status"] != RequestStatus.AWAITING_APPROVAL.value:
        raise ValueError("Request is not awaiting approval")
    try:
        role = Role(role)
    except ValueError as error:
        raise ValueError(f"Unknown approval role: {role}") from error
    decision = json.loads(request.get("decision_json") or "{}")
    required = [Role(value) for value in decision.get("required_roles", [])]
    if role not in required:
        raise ValueError(f"Role {role.value} is not required for this request")
    if verdict not in ("approve", "reject"):
        raise ValueError("Verdict must be approve or reject")
    if not _identity(approver_id, role, request["requester_id"]):
        raise PermissionError(f"{approver_id} does not hold {role.value} for this request")
    timestamp = datetime.now(timezone.utc).isoformat()
    try:
        with db.connection() as conn:
            conn.execute(
                "INSERT INTO approvals(request_id,role,approver_id,verdict,comment,ts) VALUES(?,?,?,?,?,?)",
                (request_id, role.value, approver_id, verdict, comment, timestamp),
            )
    except sqlite3.IntegrityError as error:
        if "UNIQUE constraint failed" in str(error):
            raise ValueError(f"An approval for role {role.value} already exists") from error
        raise
    verb = "approved" if verdict == "approve" else "rejected"
    yield _event(
        request_id, verdict, "ok", f"{role.value.title()} {verb}",
        {"approver_id": approver_id, "role": role.value, "verdict": verdict, "comment": comment},
    )
    approvals = db.get_approvals(request_id)
    if verdict == "reject":
        db.save_request(request_id, status=RequestStatus.REJECTED.value)
        yield _event(request_id, "status", "ok", "Request rejected by approver", {"role": role.value})
        return
    approved = {item["role"] for item in approvals if item["verdict"] == "approve"}
    if {role.value for role in required} <= approved:
        db.save_request(request_id, status=RequestStatus.APPROVED.value)
        yield _event(request_id, "status", "ok", "All required roles approved; executing", {})
        yield from resume_after_approval(request_id)