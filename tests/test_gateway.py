import json
from datetime import datetime, timezone

import pytest

from approva import db
from approva.approvals import submit
from approva.gateway import (
    EXECUTOR_ACTOR, AuthorizationResult, AuthorizationState, authorize_action,
    authorize_request,
)
from approva.orchestrator import create_request, process_request
from approva.tools.registry import call_tool
from approva.tools.ticketing import create_ticket

SCENARIO_A = "Need Figma licenses for 5 designers, ~₹6,300/seat/month, starting Monday."


def prepare_request(monkeypatch, tmp_path, name="gateway.db"):
    """Build a seeded, processed Scenario A request in a temporary DB."""
    monkeypatch.setenv("LLM_MODE", "stub")
    monkeypatch.setenv("APPROVA_DB", str(tmp_path / name))
    db.seed_from_yaml()
    request_id = create_request("E001", SCENARIO_A)
    list(process_request(request_id))
    return request_id


def add_manager_approval(request_id: str, approver_id: str = "E002") -> None:
    """Record a manager approval and set the request to the authorized state."""
    with db.connection() as conn:
        conn.execute(
            "INSERT INTO approvals(request_id,role,approver_id,verdict,ts) VALUES(?,?,?,?,?)",
            (request_id, "manager", approver_id, "approve", datetime.now(timezone.utc).isoformat()),
        )
    db.save_request(request_id, status="APPROVED")


def ticket_arguments(request_id: str) -> dict:
    """Return the executor's ordinary IT ticket arguments for Scenario A."""
    request = db.get_request(request_id)
    parsed = json.loads(request["parsed_json"])
    return {
        "request_id": request_id,
        "queue": "IT",
        "title": f"Software request {request_id}",
        "body": parsed["summary"],
    }


def test_gateway_blocks_before_approval_and_for_non_executor(monkeypatch, tmp_path):
    request_id = prepare_request(monkeypatch, tmp_path)
    request = db.get_request(request_id)
    decision = json.loads(request["decision_json"])
    args = ticket_arguments(request_id)

    pending = authorize_action(request_id, decision, [], EXECUTOR_ACTOR, "create_ticket", args)
    impersonated = authorize_action(
        request_id, decision, [], {"id": "E002", "role": "manager"}, "create_ticket", args
    )
    assert pending.state == AuthorizationState.BLOCK
    assert "state AWAITING_APPROVAL" in pending.reason
    assert impersonated.state == AuthorizationState.BLOCK
    assert "Executor" in impersonated.reason


def test_gateway_allows_only_matching_executor_permit_and_binds_arguments(monkeypatch, tmp_path):
    request_id = prepare_request(monkeypatch, tmp_path)
    add_manager_approval(request_id)
    request = db.get_request(request_id)
    decision = json.loads(request["decision_json"])
    approvals = db.get_approvals(request_id)
    args = ticket_arguments(request_id)
    permit = authorize_action(request_id, decision, approvals, EXECUTOR_ACTOR, "create_ticket", args)
    assert permit.state == AuthorizationState.ALLOW

    result = call_tool(
        "create_ticket", authorization=permit, request_type="software_license", **args
    )
    assert result["ref_id"] == "TKT-0001"
    substituted = {**args, "body": "different request content"}
    changed = authorize_action(
        request_id, decision, approvals, EXECUTOR_ACTOR, "create_ticket", substituted
    )
    assert changed.state == AuthorizationState.BLOCK
    assert "deterministic request plan" in changed.reason
    with pytest.raises(PermissionError, match="matching ALLOW permit"):
        call_tool("create_ticket", authorization=None, request_type="software_license", **args)
    with pytest.raises(PermissionError, match="Gateway ALLOW permit"):
        create_ticket(
            request_id=request_id, queue="IT", title="Direct call", body="Must not dispatch",
            authorization=None,
        )
    forged = AuthorizationResult(
        state=AuthorizationState.ALLOW, request_id=request_id,
        actor_id=EXECUTOR_ACTOR["id"], tool_name="create_ticket",
        arguments_json=permit.arguments_json, idempotency_key=permit.idempotency_key,
        reason="forged",
    )
    with pytest.raises(PermissionError, match="invalid or forged"):
        call_tool("create_ticket", authorization=forged, request_type="software_license", **args)
    changed = {**args, "queue": "Manual Review"}
    with pytest.raises(PermissionError, match="matching ALLOW permit"):
        call_tool("create_ticket", authorization=permit, request_type="software_license", **changed)


def test_gateway_holds_duplicate_action_and_blocks_wrong_historical_manager(monkeypatch, tmp_path):
    request_id = prepare_request(monkeypatch, tmp_path)
    add_manager_approval(request_id)
    request = db.get_request(request_id)
    decision = json.loads(request["decision_json"])
    args = ticket_arguments(request_id)
    first = authorize_action(request_id, decision, db.get_approvals(request_id), EXECUTOR_ACTOR, "create_ticket", args)
    with db.connection() as conn:
        conn.execute(
            "INSERT INTO tool_calls(idem_key,request_id,tool,args_json,ok,ref_id,message,ts) VALUES(?,?,?,?,?,?,?,?)",
            (first.idempotency_key, request_id, "create_ticket", first.arguments_json, 1, "TKT-0001", "created", datetime.now(timezone.utc).isoformat()),
        )
    duplicate = authorize_action(request_id, decision, db.get_approvals(request_id), EXECUTOR_ACTOR, "create_ticket", args)
    assert duplicate.state == AuthorizationState.HOLD
    assert duplicate.ref_id == "TKT-0001"

    other_path = tmp_path / "wrong-manager.db"
    request_id = prepare_request(monkeypatch, tmp_path, other_path.name)
    add_manager_approval(request_id, "E007")
    request = db.get_request(request_id)
    blocked = authorize_action(
        request_id, json.loads(request["decision_json"]), db.get_approvals(request_id),
        EXECUTOR_ACTOR, "create_ticket", ticket_arguments(request_id),
    )
    assert blocked.state == AuthorizationState.BLOCK
    assert "identity is invalid" in blocked.reason


def test_gateway_blocks_reject_decision_and_nonallowlisted_tool(monkeypatch, tmp_path):
    request_id = prepare_request(monkeypatch, tmp_path)
    add_manager_approval(request_id)
    request = db.get_request(request_id)
    decision = json.loads(request["decision_json"])
    args = ticket_arguments(request_id)
    rejected = {**decision, "type": "REJECT"}
    db.save_request(request_id, decision_json=json.dumps(rejected))
    result = authorize_action(request_id, rejected, db.get_approvals(request_id), EXECUTOR_ACTOR, "create_ticket", args)
    assert result.state == AuthorizationState.BLOCK
    assert "cannot execute" in result.reason
    db.save_request(request_id, decision_json=json.dumps(decision))
    unknown = authorize_action(request_id, decision, db.get_approvals(request_id), EXECUTOR_ACTOR, "send_payment", args)
    assert unknown.state == AuthorizationState.BLOCK
    assert "not allowlisted" in unknown.reason


def test_gateway_rejects_decision_that_weakens_persisted_requirements(monkeypatch, tmp_path):
    request_id = prepare_request(monkeypatch, tmp_path)
    add_manager_approval(request_id)
    request = db.get_request(request_id)
    persisted = json.loads(request["decision_json"])
    weakened = {**persisted, "type": "AUTO_APPROVE", "required_roles": []}
    permit = authorize_action(
        request_id, weakened, db.get_approvals(request_id), EXECUTOR_ACTOR,
        "create_ticket", ticket_arguments(request_id),
    )
    assert permit.state == AuthorizationState.BLOCK
    assert "differs from the persisted decision" in permit.reason


def test_gateway_only_allows_manual_handoff_ticket_in_manual_review(monkeypatch, tmp_path):
    request_id = prepare_request(monkeypatch, tmp_path)
    db.save_request(request_id, status="MANUAL_REVIEW")
    args = {
        "request_id": request_id, "queue": "Manual Review",
        "title": f"Approva could not process request {request_id}", "body": SCENARIO_A,
    }
    allowed = authorize_action(request_id, {}, [], EXECUTOR_ACTOR, "create_ticket", args)
    rejected = authorize_action(
        request_id, {}, [], EXECUTOR_ACTOR, "provision_license",
        {"request_id": request_id, "vendor": "Figma"},
    )
    assert allowed.state == AuthorizationState.ALLOW
    assert rejected.state == AuthorizationState.BLOCK