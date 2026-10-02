import json

from approva import audit, db
from approva.orchestrator import create_request, process_request

SCENARIO_A = "Need Figma licenses for 5 designers, ~₹6,300/seat/month, starting Monday."


def test_scenario_a_streams_audited_steps_to_approval(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_MODE", "stub")
    monkeypatch.setenv("APPROVA_DB", str(tmp_path / "pipeline.db"))
    db.seed_from_yaml()
    request_id = create_request("E001", SCENARIO_A)
    events = list(process_request(request_id))
    request = db.get_request(request_id)

    assert request["status"] == "AWAITING_APPROVAL"
    decision = json.loads(request["decision_json"])
    assert decision["type"] == "REQUIRE_APPROVAL"
    assert decision["required_roles"] == ["manager"]
    assert [event.step for event in events][0] == "plan"
    assert {"intake", "policy", "matrix", "risk", "decision"} <= {event.step for event in events}
    for step in ("intake", "policy", "matrix", "risk", "decision"):
        assert [event.status for event in events if event.step == step] == ["started", "ok"]
    assert audit.verify_chain() == (True, None)


def test_llm_failure_fails_closed_with_manual_review_ticket(monkeypatch, tmp_path):
    from approva import orchestrator
    from approva.llm import ServiceUnavailable

    monkeypatch.setenv("LLM_MODE", "stub")
    monkeypatch.setenv("APPROVA_DB", str(tmp_path / "failclosed.db"))
    db.seed_from_yaml()
    request_id = create_request("E001", SCENARIO_A)

    def unavailable(*args, **kwargs):
        raise ServiceUnavailable("simulated outage")

    monkeypatch.setattr(orchestrator, "parse_request", unavailable)
    events = list(process_request(request_id))
    request = db.get_request(request_id)
    with db.connection() as conn:
        ticket = conn.execute("SELECT * FROM tickets WHERE request_id=?", (request_id,)).fetchone()

    assert request["status"] == "MANUAL_REVIEW"
    assert ticket["queue"] == "Manual Review"
    assert ticket["body"] == SCENARIO_A
    assert events[-1].status == "failed"
    assert audit.verify_chain() == (True, None)