"""Guarded Executor and idempotent dispatch for mock workflow tools."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Iterator

from approva import audit, db
from approva.gateway import (
    EXECUTOR_ACTOR, AuthorizationState, authorize_action, authorize_request,
)
from approva.schemas import DecisionType, RequestStatus, TraceEvent
from approva.tools.registry import call_tool


class PermissionViolation(RuntimeError):
    """Raised when a request is not authorized for execution."""


def create_manual_review_ticket(request_id: str, raw_text: str) -> str:
    """Route an unprocessable request to the Manual Review queue."""
    arguments = {
        "request_id": request_id,
        "queue": "Manual Review",
        "title": f"Approva could not process request {request_id}",
        "body": raw_text,
    }
    permit = authorize_action(request_id, {}, [], EXECUTOR_ACTOR, "create_ticket", arguments)
    if permit.state == AuthorizationState.HOLD:
        return permit.ref_id or ""
    if permit.state != AuthorizationState.ALLOW:
        raise PermissionViolation(permit.reason)
    result = call_tool("create_ticket", authorization=permit, request_type="unknown", **arguments)
    return result["ref_id"]


def _event(request_id: str, step: str, status: str, summary: str, detail=None) -> TraceEvent:
    """Append one executor event to the audit chain."""
    return audit.append(TraceEvent(
        request_id=request_id, ts=datetime.now(timezone.utc), agent="executor",
        step=step, status=status, summary=summary, detail=detail or {},
    ))


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
    request_permit = authorize_request(request_id, decision, approvals, EXECUTOR_ACTOR)
    if request_permit.state != AuthorizationState.ALLOW:
        failure = _event(
            request_id, "guard", "failed", "PermissionViolation: execution attempted without valid approvals",
            {"status": request["status"], "decision": decision, "reason": request_permit.reason},
        )
        yield failure
        raise PermissionViolation(request_id)

    parsed = json.loads(request["parsed_json"])
    request_type = parsed["request_type"]
    execution_started = request["status"] == RequestStatus.EXECUTING.value
    for name, arguments in _tool_plan(request, parsed):
        complete_args = {"request_id": request_id, **arguments}
        permit = authorize_action(request_id, decision, approvals, EXECUTOR_ACTOR, name, complete_args)
        if permit.state == AuthorizationState.HOLD:
            yield _event(request_id, name, "warn", "Tool already completed; skipped duplicate", {"ref_id": permit.ref_id})
            continue
        if permit.state != AuthorizationState.ALLOW:
            yield _event(request_id, "guard", "failed", "PermissionViolation: gateway blocked tool action", {
                "tool": name, "reason": permit.reason,
            })
            raise PermissionViolation(permit.reason)
        if not execution_started:
            db.save_request(request_id, status=RequestStatus.EXECUTING.value)
            request["status"] = RequestStatus.EXECUTING.value
            execution_started = True
            yield _event(request_id, "guard", "ok", "Execution guard passed")
        yield _event(request_id, name, "started", f"{name} started")
        try:
            result = call_tool(
                name, authorization=permit, request_type=request_type, **complete_args
            )
        except Exception as error:
            with db.connection() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO tool_calls(idem_key,request_id,tool,args_json,ok,ref_id,message,ts) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (permit.idempotency_key, request_id, name, permit.arguments_json, 0, None, str(error), datetime.now(timezone.utc).isoformat()),
                )
            db.save_request(request_id, status=RequestStatus.FAILED.value)
            yield _event(request_id, name, "failed", f"{name} failed: {type(error).__name__}")
            return
        warning = result.get("warning", False)
        with db.connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO tool_calls(idem_key,request_id,tool,args_json,ok,ref_id,message,ts) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (permit.idempotency_key, request_id, name, permit.arguments_json, 1, result.get("ref_id"), result.get("message", ""), datetime.now(timezone.utc).isoformat()),
            )
        yield _event(request_id, name, "warn" if warning else "ok", result.get("message", f"{name} completed"), result)
    db.save_request(request_id, status=RequestStatus.COMPLETED.value)
    yield _event(request_id, "complete", "ok", "Request execution completed")