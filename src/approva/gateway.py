"""Single authorization boundary for every side-effecting tool invocation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from approva import audit, db
from approva.schemas import Decision, DecisionType, RequestStatus, Role, TraceEvent

EXECUTOR_ACTOR = {"id": "approva-executor", "role": "executor"}
_PERMIT_PROOF = object()


class AuthorizationState(str, Enum):
    """Outcome returned by the Decision Gateway."""

    ALLOW = "ALLOW"
    HOLD = "HOLD"
    BLOCK = "BLOCK"


@dataclass(frozen=True)
class AuthorizationResult:
    """Permit or denial bound to one request, actor, tool, and canonical argument set."""

    state: AuthorizationState
    request_id: str
    actor_id: str
    tool_name: str
    arguments_json: str
    idempotency_key: str
    reason: str
    ref_id: str | None = None
    _proof: object = field(repr=False, compare=False, default=None)


def _canonical(arguments: dict) -> str:
    """Serialize a tool argument mapping consistently for hashing and permit checks."""
    return json.dumps(arguments, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _identity_holds_role(approver_id: str, role: str, requester_id: str) -> bool:
    """Revalidate a recorded approval against seeded role and reporting-line data."""
    with db.connection() as conn:
        approver = conn.execute("SELECT role FROM employees WHERE id=?", (approver_id,)).fetchone()
        requester = conn.execute("SELECT manager_id FROM employees WHERE id=?", (requester_id,)).fetchone()
    if not approver or not requester:
        return False
    if role == Role.MANAGER.value:
        return approver["role"] == role and requester["manager_id"] == approver_id
    return approver["role"] == role


def _log(request_id: str, tool_name: str, state: AuthorizationState, reason: str, key: str) -> None:
    """Append a tamper-evident authorization outcome without recording raw tool arguments."""
    status = "ok" if state == AuthorizationState.ALLOW else "warn" if state == AuthorizationState.HOLD else "failed"
    audit.append(TraceEvent(
        request_id=request_id,
        ts=datetime.now(timezone.utc),
        agent="executor",
        step="gateway.authorize",
        status=status,
        summary=f"Gateway {state.value}: {reason}",
        detail={"tool": tool_name, "idempotency_key": key, "result": state.value, "reason": reason},
    ))


def _result(
    request_id: str,
    actor_id: str,
    tool_name: str,
    arguments_json: str,
    idempotency_key: str,
    state: AuthorizationState,
    reason: str,
    ref_id: str | None = None,
) -> AuthorizationResult:
    """Construct and audit one gateway authorization result."""
    _log(request_id, tool_name, state, reason, idempotency_key)
    return AuthorizationResult(
        state=state, request_id=request_id, actor_id=actor_id, tool_name=tool_name,
        arguments_json=arguments_json, idempotency_key=idempotency_key, reason=reason,
        ref_id=ref_id, _proof=_PERMIT_PROOF,
    )


def _request_authority(request: dict, decision: Decision | dict | str, approvals: list[dict], actor: dict) -> tuple[Decision | None, str | None]:
    """Validate request state, executor identity, decision, and every recorded approval."""
    if actor != EXECUTOR_ACTOR:
        return None, "actor is not the Approva Executor"
    if request["status"] not in (RequestStatus.APPROVED.value, RequestStatus.EXECUTING.value):
        return None, f"request state {request['status']} cannot execute"
    try:
        validated_decision = decision if isinstance(decision, Decision) else Decision.model_validate_json(decision) if isinstance(decision, str) else Decision.model_validate(decision)
    except (ValueError, TypeError):
        return None, "decision is invalid"
    try:
        persisted_decision = Decision.model_validate_json(request.get("decision_json") or "")
    except ValueError:
        return None, "persisted request decision is invalid"
    if validated_decision != persisted_decision:
        return None, "supplied decision differs from the persisted decision"
    if any(approval.get("verdict") == "reject" for approval in approvals):
        return None, "a required approver rejected"
    approved_roles = set()
    for approval in approvals:
        role = approval.get("role")
        approver_id = approval.get("approver_id")
        if role not in {item.value for item in Role} or not _identity_holds_role(approver_id, role, request["requester_id"]):
            return None, "recorded approver identity is invalid"
        if approval.get("verdict") == "approve":
            approved_roles.add(role)
    required = {role.value for role in validated_decision.required_roles}
    if validated_decision.type == DecisionType.AUTO_APPROVE:
        if required:
            return None, "auto-approval decision contains required roles"
    elif validated_decision.type in (DecisionType.REQUIRE_APPROVAL, DecisionType.ESCALATE):
        if not required <= approved_roles:
            return None, "mandatory approval roles are not satisfied"
    else:
        return None, f"decision {validated_decision.type.value} cannot execute"
    return validated_decision, None


def authorize_request(
    request_id: str,
    decision: Decision | dict | str,
    approvals: list[dict],
    actor: dict,
) -> AuthorizationResult:
    """Authorize the overall request before the Executor builds a tool plan."""
    arguments_json = "{}"
    key = hashlib.sha256((request_id + "__request__" + arguments_json).encode("utf-8")).hexdigest()
    request = db.get_request(request_id)
    if request is None:
        return _result(request_id, str(actor.get("id", "")), "__request__", arguments_json, key, AuthorizationState.BLOCK, "request not found")
    _, reason = _request_authority(request, decision, approvals, actor)
    if reason:
        return _result(request_id, str(actor.get("id", "")), "__request__", arguments_json, key, AuthorizationState.BLOCK, reason)
    return _result(request_id, str(actor.get("id", "")), "__request__", arguments_json, key, AuthorizationState.ALLOW, "request authority checks passed")


def authorize_action(
    request_id: str,
    decision: Decision | dict | str,
    approvals: list[dict],
    actor: dict,
    tool_name: str,
    tool_args: dict,
) -> AuthorizationResult:
    """Authorize one tool action after rechecking request, decision, approvals, actor, and idempotency."""
    arguments_json = _canonical(tool_args)
    key = hashlib.sha256((request_id + tool_name + arguments_json).encode("utf-8")).hexdigest()
    actor_id = str(actor.get("id", ""))
    request = db.get_request(request_id)
    if request is None:
        return _result(request_id, actor_id, tool_name, arguments_json, key, AuthorizationState.BLOCK, "request not found")
    if request["status"] == RequestStatus.MANUAL_REVIEW.value:
        if actor != EXECUTOR_ACTOR:
            return _result(request_id, actor_id, tool_name, arguments_json, key, AuthorizationState.BLOCK, "actor is not the Approva Executor")
        manual_handoff = tool_name == "create_ticket" and tool_args.get("queue") == "Manual Review"
        if not manual_handoff:
            return _result(request_id, actor_id, tool_name, arguments_json, key, AuthorizationState.BLOCK, "manual-review state permits only its handoff ticket")
        expected_handoff = {
            "request_id": request_id,
            "queue": "Manual Review",
            "title": f"Approva could not process request {request_id}",
            "body": request["raw_text"],
        }
        if arguments_json != _canonical(expected_handoff):
            return _result(request_id, actor_id, tool_name, arguments_json, key, AuthorizationState.BLOCK, "manual-review ticket does not match the original request")
        with db.connection() as conn:
            ticket = conn.execute(
                "SELECT id FROM tickets WHERE request_id=? AND queue='Manual Review' ORDER BY ts LIMIT 1",
                (request_id,),
            ).fetchone()
        if ticket:
            return _result(request_id, actor_id, tool_name, arguments_json, key, AuthorizationState.HOLD, "manual-review ticket already exists", ticket["id"])
        return _result(request_id, actor_id, tool_name, arguments_json, key, AuthorizationState.ALLOW, "manual-review handoff")

    validated_decision, authority_error = _request_authority(request, decision, approvals, actor)
    if authority_error:
        return _result(request_id, actor_id, tool_name, arguments_json, key, AuthorizationState.BLOCK, authority_error)
    assert validated_decision is not None
    parsed = json.loads(request.get("parsed_json") or "{}")
    request_type = parsed.get("request_type")
    from approva.tools.registry import REGISTRY

    registered = REGISTRY.get(tool_name)
    if not registered or not registered.side_effect or request_type not in registered.allowed_in:
        return _result(request_id, actor_id, tool_name, arguments_json, key, AuthorizationState.BLOCK, "tool is not allowlisted for this workflow")
    if tool_args.get("request_id") != request_id:
        return _result(request_id, actor_id, tool_name, arguments_json, key, AuthorizationState.BLOCK, "tool request binding does not match")
    from approva.executor import _tool_plan

    expected_arguments = next((arguments for name, arguments in _tool_plan(request, parsed) if name == tool_name and _canonical({"request_id": request_id, **arguments}) == arguments_json), None)
    if expected_arguments is None:
        return _result(request_id, actor_id, tool_name, arguments_json, key, AuthorizationState.BLOCK, "tool arguments differ from the deterministic request plan")

    with db.connection() as conn:
        prior = conn.execute("SELECT ok,ref_id FROM tool_calls WHERE idem_key=?", (key,)).fetchone()
    if prior and prior["ok"]:
        return _result(request_id, actor_id, tool_name, arguments_json, key, AuthorizationState.HOLD, "idempotent action already completed", prior["ref_id"])
    return _result(request_id, actor_id, tool_name, arguments_json, key, AuthorizationState.ALLOW, "decision and authority checks passed")


def validate_permit(permit: AuthorizationResult, tool_name: str, arguments: dict) -> bool:
    """Check that a permit exactly matches the tool invocation being dispatched."""
    return bool(
        isinstance(permit, AuthorizationResult)
        and permit._proof is _PERMIT_PROOF
        and permit.state == AuthorizationState.ALLOW
        and permit.actor_id == EXECUTOR_ACTOR["id"]
        and permit.tool_name == tool_name
        and permit.arguments_json == _canonical(arguments)
        and permit.request_id == arguments.get("request_id")
    )


def require_permit(permit: AuthorizationResult, tool_name: str, arguments: dict) -> None:
    """Reject direct tool-function calls that lack a matching Gateway permit."""
    if not validate_permit(permit, tool_name, arguments):
        raise PermissionError("Side-effecting tool requires a matching Gateway ALLOW permit")