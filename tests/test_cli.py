import sys

from approva import audit, db
from approva.cli import main
from approva.orchestrator import create_request, process_request


def test_cli_status_and_audit_tamper_commands(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("LLM_MODE", "stub")
    monkeypatch.setenv("APPROVA_DB", str(tmp_path / "cli.db"))
    db.seed_from_yaml()
    request_id = create_request("E001", "Need Figma licenses for 5 designers, ~₹6,300/seat/month, starting Monday.")
    list(process_request(request_id))

    monkeypatch.setattr(sys, "argv", ["approva", "status", request_id])
    assert main() == 0
    assert "AWAITING_APPROVAL" in capsys.readouterr().out

    monkeypatch.setattr(sys, "argv", ["approva", "audit-verify"])
    assert main() == 0
    assert "Audit chain OK" in capsys.readouterr().out

    monkeypatch.setattr(sys, "argv", ["approva", "tamper", "1"])
    assert main() == 0
    assert "Tampered" in capsys.readouterr().out

    monkeypatch.setattr(sys, "argv", ["approva", "audit-verify"])
    assert main() == 1
    assert "broken at seq 1" in capsys.readouterr().out
    assert audit.verify_chain() == (False, 1)


def test_cli_reset_keeps_seed_reference_data(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("APPROVA_DB", str(tmp_path / "reset.db"))
    db.seed_from_yaml()
    db.save_request("REQ-0001", status="RECEIVED")
    monkeypatch.setattr(sys, "argv", ["approva", "reset"])
    assert main() == 0
    with db.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0] == 8
    assert "reset" in capsys.readouterr().out.lower()