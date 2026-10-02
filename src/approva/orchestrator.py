"""Plan, execute, persist, and audit the tier-one request pipeline."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Callable, Iterator

from approva import audit, db
from approva.agents.intake import parse_request
from approva.agents.policy import evaluate_policy
from approva.agents.summary import approver_summary
from approva.engine.costs import annualized_cost
from approva.engine.decision import decide
from approva.engine.matrix import matrix_roles_with_clauses
from approva.engine.risk import score_risk
from approva.executor import create_manual_review_ticket, run as execute
from approva.schemas import Decision, DecisionType, RequestStatus, TraceEvent

PLAN = ["intake", "policy", "matrix", "risk", "decision", "summary", "await_approval_or_execute"]


def _now() -> str:
    """Return an ISO UTC timestamp for persistence."""
    return datetime.now(timezone.utc).isoformat()


def create_request(requester_id: str, raw_text: str) -> str:
    """Persist a new request in RECEIVED status and return its ID."""
    db.init_db()
    request_id = db.next_id("REQ")
    timestamp = _now()
    db.save_request(
        request_id, requester_id=requester_id, raw_text=raw_text,
        status=RequestStatus.RECEIVED.value, created_at=timestamp, updated_at=timestamp,
        pipeline_tier="claude", degraded=0,
    )
    return request_id


def _emit(request: dict, agent: str, step: str, status: str, summary: str, detail=None, **meta) -> TraceEvent:
    """Append and return one audit-backed pipeline event."""
    event = TraceEvent(
        request_id=request["id"], ts=datetime.now(timezone.utc), agent=agent,
        step=step, status=status, summary=summary, detail=detail or {}, **meta,
    )
    return audit.append(event)


def _save_json(request_id: str, column: str, value: object) -> None:
    """Persist a model or JSON-compatible step result to its request field."""
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    db.save_request(request_id, updated_at=_now(), **{column: json.dumps(value, ensure_ascii=False)})


def _run_step(
    request: dict,
    agent: str,
    step: str,
    operation: Callable[[], tuple[object, dict]],
    column: str | None = None,
) -> Iterator[TraceEvent]:
    """Yield lifecycle events around one persisted pipeline operation."""
    yield _emit(request, agent, step, "started", f"{step} started")
    started = time.perf_counter()
    try:
        result, meta = operation()
    except Exception as error:
        yield _emit(request, agent, step, "failed", f"{step} failed: {type(error).__name__}", {"error": str(error)})
        raise
    elapsed = int((time.perf_counter() - started) * 1000)
    if column:
        _save_json(request["id"], column, result)
    summary = f"{step} completed"
    if step == "decision":
        summary = f"Decision: {result.type.value}"
    elif step == "risk":
        summary = f"Risk score {result.score} ({result.tier})"
    elif step == "matrix":
        summary = f"Required roles: {', '.join(result['roles']) or 'none'}"
    yield _emit(
        request, agent, step, "ok", summary, {"result": result.model_dump(mode="json") if hasattr(result, "model_dump") else result},
        latency_ms=meta.get("latency_ms", elapsed), tokens_in=meta.get("tokens_in"),
        tokens_out=meta.get("tokens_out"),
    )
    return result, meta


def _employee_context(requester_id: str) -> tuple[str, str]:
    """Load a requester's display name and department from the seed table."""
    with db.connection() as conn:
        row = conn.execute("SELECT name,department FROM employees WHERE id=?", (requester_id,)).fetchone()
    return (row["name"], row["department"]) if row else (requester_id, "")


def _set_status(request: dict, status: RequestStatus) -> None:
    """Persist a request state transition and refresh its timestamp."""
    db.save_request(request["id"], status=status.value, updated_at=_now())
    request["status"] = status.value


def _fail_closed(request: dict, error: Exception) -> Iterator[TraceEvent]:
    """Create a Manual Review ticket and end the request without approval."""
    _set_status(request, RequestStatus.MANUAL_REVIEW)
    ticket_id = create_manual_review_ticket(request["id"], request["raw_text"])
    yield _emit(
        request, "orchestrator", "fail_closed", "failed",
        "We couldn't process this automatically; it's been routed to a human.",
        {"error": type(error).__name__, "message": str(error), "ticket_id": ticket_id},
    )


def _apply_decision(request: dict, decision: Decision) -> Iterator[TraceEvent]:
    """Set the terminal or approval-waiting state and start safe execution."""
    if decision.type == DecisionType.AUTO_APPROVE:
        _set_status(request, RequestStatus.APPROVED)
        yield _emit(request, "orchestrator", "status", "ok", "Request approved automatically")
        yield from execute(request["id"])
    elif decision.type in (DecisionType.REQUIRE_APPROVAL, DecisionType.ESCALATE):
        _set_status(request, RequestStatus.AWAITING_APPROVAL)
        yield _emit(request, "orchestrator", "status", "ok", "Waiting for required human approvals")
    elif decision.type == DecisionType.REJECT:
        _set_status(request, RequestStatus.REJECTED)
        yield _emit(request, "orchestrator", "status", "ok", "Request rejected by policy")
    else:
        _set_status(request, RequestStatus.NEEDS_INFO)
        yield _emit(request, "orchestrator", "status", "ok", "Additional information is required")


def process_request(request_id: str) -> Iterator[TraceEvent]:
    """Run the intake-to-decision pipeline and fail closed on unrecoverable errors."""
    request = db.get_request(request_id)
    if request is None:
        raise ValueError(f"Request not found: {request_id}")
    try:
        _save_json(request_id, "plan_json", PLAN)
        yield _emit(request, "orchestrator", "plan", "ok", "Plan: " + " -> ".join(PLAN), {"steps": PLAN})
        requester_name, department = _employee_context(request["requester_id"])
        parsed, _ = yield from _run_step(
            request, "intake", "intake",
            lambda: parse_request(request["raw_text"], requester_name, department), "parsed_json",
        )
        cost = annualized_cost(parsed)
        vendor = parsed.vendor_or_payee
        if parsed.request_type.value == "expense_claim" and vendor is None:
            vendor_status = "approved"
        else:
            from approva.engine.vendors import lookup_vendor_status

            vendor_status = lookup_vendor_status(vendor)
        db.save_request(request_id, annual_cost=cost, vendor_status=vendor_status)
        policy, policy_meta = yield from _run_step(
            request, "policy", "policy",
            lambda: evaluate_policy(parsed, cost, vendor_status), "policy_json",
        )
        for warning in policy_meta.get("warnings", []):
            yield _emit(request, "policy", "validation", "warn", warning)
        roles, clauses = matrix_roles_with_clauses(parsed, cost, vendor_status)
        matrix_result = {"roles": [role.value for role in roles], "clauses": clauses}
        yield from _run_step(
            request, "matrix", "matrix", lambda: (matrix_result, {}),
        )
        risk, _ = yield from _run_step(
            request, "risk", "risk",
            lambda: (score_risk(parsed, cost, vendor_status), {}), "risk_json",
        )
        decision, _ = yield from _run_step(
            request, "decision", "decision",
            lambda: (decide(parsed, policy, risk, cost, vendor_status), {}), "decision_json",
        )
        summary = approver_summary(parsed, policy, risk, decision, cost, vendor_status)
        _save_json(request_id, "brief_json", summary)
        yield _emit(request, "brief", "summary", "ok", "Prepared deterministic approver summary", {"summary": summary})
        yield from _apply_decision(request, decision)
    except Exception as error:
        yield from _fail_closed(request, error)


def resume_after_approval(request_id: str) -> Iterator[TraceEvent]:
    """Resume the approved request through the guarded Executor."""
    yield from execute(request_id)