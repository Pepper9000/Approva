import json

import pytest

from approva import db
from approva.approvals import submit
from approva.orchestrator import create_request, process_request

SCENARIO_A = "Need Figma licenses for 5 designers, ~₹6,300/seat/month, starting Monday."
SCENARIO_C = "We need VoxLens AI for sales to analyse customer calls. ₹40 lakh per year. It records customer calls."


def prepare_request(monkeypatch, tmp_path, name, text):
    """Seed a temporary DB and process one request in stub mode."""
    monkeypatch.setenv("LLM_MODE", "stub")
    monkeypatch.setenv("APPROVA_DB", str(tmp_path / name))
    db.seed_from_yaml()
    request_id = create_request("E001", text)
    list(process_request(request_id))
    return request_id


def test_wrong_role_and_wrong_manager_are_rejected(monkeypatch, tmp_path):
    request_id = prepare_request(monkeypatch, tmp_path, "identity.db", SCENARIO_A)
    with pytest.raises(ValueError, match="not required"):
        list(submit(request_id, "E002", "finance", "approve"))
    with pytest.raises(PermissionError, match="does not hold manager"):
        list(submit(request_id, "E007", "manager", "approve"))
    assert db.get_request(request_id)["status"] == "AWAITING_APPROVAL"


def test_duplicate_role_approval_is_rejected(monkeypatch, tmp_path):
    request_id = prepare_request(monkeypatch, tmp_path, "duplicate.db", SCENARIO_C)
    list(submit(request_id, "E002", "manager", "approve"))
    with pytest.raises(ValueError, match="already exists"):
        list(submit(request_id, "E002", "manager", "approve"))


def test_any_rejection_ends_multi_role_request(monkeypatch, tmp_path):
    request_id = prepare_request(monkeypatch, tmp_path, "reject.db", SCENARIO_C)
    events = list(submit(request_id, "E002", "manager", "reject", "Please review the need."))
    assert db.get_request(request_id)["status"] == "REJECTED"
    assert events[0].detail["verdict"] == "reject"
    with db.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM tool_calls WHERE request_id=?", (request_id,)).fetchone()[0] == 0


def test_all_four_roles_approve_before_execution(monkeypatch, tmp_path):
    request_id = prepare_request(monkeypatch, tmp_path, "multi-role.db", SCENARIO_C)
    assert json.loads(db.get_request(request_id)["decision_json"])["required_roles"] == [
        "manager", "finance", "legal", "security",
    ]
    for approver_id, role in (("E002", "manager"), ("E004", "finance"), ("E005", "legal"), ("E003", "security")):
        list(submit(request_id, approver_id, role, "approve"))
    assert db.get_request(request_id)["status"] == "COMPLETED"