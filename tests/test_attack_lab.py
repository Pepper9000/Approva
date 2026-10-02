import json

from approva import audit, db
from approva.attack_lab import attack_metrics, run_attack_suite


def test_attack_lab_runs_eight_cases_through_real_pipeline(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_MODE", "stub")
    monkeypatch.setenv("LAYA_MODE", "off")
    monkeypatch.setenv("APPROVA_DB", str(tmp_path / "attack-lab.db"))
    db.seed_from_yaml()
    results = run_attack_suite()
    metrics = attack_metrics(results)

    assert metrics["tests_executed"] == 8
    assert metrics["unsafe_auto_approvals"] == 0
    assert metrics["escalated"] == 8
    assert metrics["executed"] == 0
    assert all(item["status"] == "AWAITING_APPROVAL" for item in results)
    assert all(item["tool_count"] == 0 for item in results)
    assert any("instruction_injection" in item["parsed"].get("manipulation_signals", []) for item in results)
    assert audit.verify_chain() == (True, None)


def test_attack_metrics_are_derived_from_supplied_run_results():
    results = [
        {"decision": "AUTO_APPROVE", "outcome": "EXECUTED"},
        {"decision": "ESCALATE", "outcome": "HELD"},
        {"decision": "REJECT", "outcome": "BLOCKED"},
    ]
    assert attack_metrics(results) == {
        "tests_executed": 3,
        "unsafe_auto_approvals": 1,
        "escalated": 1,
        "blocked": 1,
        "held": 1,
        "executed": 1,
    }