"""Guarded Executor and idempotent dispatch for mock workflow tools."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Iterator

from approva import audit, db
from approva.schemas import DecisionType, RequestStatus, TraceEvent
from approva.tools.registry import call_tool


class PermissionViolation(RuntimeError):
    """Raised when a request is not authorized for execution."""


def create_manual_review_ticket(request_id: str, raw_text: str) -> str:
    """Route an unprocessable request to the Manual Review queue."""
    result = call_tool(
        "create_ticket", request_id=request_id, queue="Manual Review",
        title=f"Approva could not process request {request_id}", body=raw_text,
    )
    return result["ref_id"]


def _event(request_id: str, step: str, status: str, summary: str, detail=None) -> TraceEvent:
    """Append one executor event to the audit chain."""
    return audit.append(TraceEvent(
        request_id=request_id, ts=datetime.now(timezone.utc), agent="executor",
        step=step, status=status, summary=summary, detail=detail or {},
    ))


def _authorized(request: dict, decision: dict, approvals: list[dict]) -> bool:
    """Check execution status, decision type, required roles, and rejections."""
    if request["status"] != RequestStatus.APPROVED.value:
        return False
    if any(approval["verdict"] == "reject" for approval in approvals):
        return False
    roles = set(decision.get("required_roles", []))
    approved = {approval["role"] for approval in approvals if approval["verdict"] == "approve"}
    if decision.get("type") == DecisionType.AUTO_APPROVE.value:
        return not roles
    if decision.get("type") in (DecisionType.REQUIRE_APPROVAL.value, DecisionType.ESCALATE.value):
        return roles <= approved
    return False


def _tool_key(request_id: str, name: str, arguments: dict) -> tuple[str, str]:
    """Return a stable idempotency key and canonical serialized arguments."""
    serialized = json.dumps(arguments, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    digest = hashlib.sha256((request_id + name + serialized).encode("utf-8")).hexdigest()
    return digest, serialized


def _employee(employee_id: str) -> dict:
    """Load an employee row for workflow notifications."""
    with db.connection() as conn:
        row = conn.execute("SELECT * FROM employees WHERE id=?", (employee_id,)).fetchone()
    return dict(row) if row else {"id": employee_id, "name": employee_id, "email": employee_id}


def _tool_plan(request: dict, parsed: dict) -> list[tuple[str, dict]]:
    """Build the deterministic side-effect sequence for the request type."""
    requester = _employee(request["requester_id"])
    summary = parsed["summary"]
    if parsed["request_type"] == "software_license":
        manager = _employee(requester.get("manager_id") or "")
        return [
            ("create_ticket", {"queue": "IT", "title": f"Software request {request['id']}", "body": summary}),
            ("provision_license", {
                "vendor": parsed.get("vendor_or_payee") or "Unknown",
                "item": parsed.get("item") or summary,
                "seats": parsed.get("quantity", 1), "requester_id": requester["id"],
                "start_date": parsed.get("start_date"),
            }),
            ("notify", {"channel": "outbox", "recipient": requester.get("email", requester["id"]),
                        "subject": "Software request completed", "body": summary}),
            ("notify", {"channel": "outbox", "recipient": manager.get("email", manager["id"]),
                        "subject": "Software request completed", "body": summary}),
        ]
    amount = (parsed.get("unit_cost_inr") or 0) * max(parsed.get("quantity", 1), 1)
    expense_args = {
        "payee": parsed.get("vendor_or_payee") or "Employee reimbursement",
        "amount_inr": amount,
        "category": parsed.get("expense_category") or "other",
        "requester_id": requester["id"],
    }
    return [
        ("post_ledger_entry", expense_args),
        ("schedule_reimbursement", expense_args),
        ("notify", {"channel": "outbox", "recipient": requester.get("email", requester["id"]),
                    "subject": "Expense reimbursement scheduled", "body": summary}),
    ]


def run(request_id: str) -> Iterator[TraceEvent]:
    """Guard, execute the approved tool plan idempotently, and complete the request."""
    request = db.get_request(request_id)
    if request is None:
        raise ValueError(f"Request not found: {request_id}")
    if request["status"] == RequestStatus.COMPLETED.value:
        yield _event(request_id, "idempotency", "warn", "Request already completed; no tools repeated")
        return
    decision = json.loads(request.get("decision_json") or "{}")
    approvals = db.get_approvals(request_id)
    if not _authorized(request, decision, approvals):
        failure = _event(
            request_id, "guard", "failed", "PermissionViolation: execution attempted without valid approvals",
            {"status": request["status"], "decision": decision},
        )
        yield failure
        raise PermissionViolation(request_id)

    db.save_request(request_id, status=RequestStatus.EXECUTING.value)
    yield _event(request_id, "guard", "ok", "Execution guard passed")
    parsed = json.loads(request["parsed_json"])
    request_type = parsed["request_type"]
    for name, arguments in _tool_plan(request, parsed):
        complete_args = {"request_id": request_id, **arguments}
        idem_key, args_json = _tool_key(request_id, name, complete_args)
        with db.connection() as conn:
            prior = conn.execute("SELECT ok,ref_id,message FROM tool_calls WHERE idem_key=?", (idem_key,)).fetchone()
        if prior and prior["ok"]:
            yield _event(request_id, name, "warn", "Tool already completed; skipped duplicate", {"ref_id": prior["ref_id"]})
            continue
        yield _event(request_id, name, "started", f"{name} started")
        try:
            result = call_tool(name, request_type=request_type, **complete_args)
        except Exception as error:
            with db.connection() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO tool_calls(idem_key,request_id,tool,args_json,ok,ref_id,message,ts) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (idem_key, request_id, name, args_json, 0, None, str(error), datetime.now(timezone.utc).isoformat()),
                )
            db.save_request(request_id, status=RequestStatus.FAILED.value)
            yield _event(request_id, name, "failed", f"{name} failed: {type(error).__name__}")
            return
        warning = result.get("warning", False)
        with db.connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO tool_calls(idem_key,request_id,tool,args_json,ok,ref_id,message,ts) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (idem_key, request_id, name, args_json, 1, result.get("ref_id"), result.get("message", ""), datetime.now(timezone.utc).isoformat()),
            )
        yield _event(request_id, name, "warn" if warning else "ok", result.get("message", f"{name} completed"), result)
    db.save_request(request_id, status=RequestStatus.COMPLETED.value)
    yield _event(request_id, "complete", "ok", "Request execution completed")