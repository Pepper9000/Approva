from pathlib import Path

from streamlit.testing.v1 import AppTest

from approva import db
from approva.approvals import submit
from approva.orchestrator import create_request, process_request

APP_PATH = Path(__file__).resolve().parents[1] / "app" / "pages" / "4_Decision_Passport.py"
SCENARIO_A = "Need Figma licenses for 5 designers, ~₹6,300/seat/month, starting Monday."


def test_passport_shows_validated_evidence_approval_gateway_and_integrity(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_MODE", "stub")
    monkeypatch.setenv("LAYA_MODE", "off")
    monkeypatch.setenv("APPROVA_DB", str(tmp_path / "passport.db"))
    db.seed_from_yaml()
    request_id = create_request("E001", SCENARIO_A)
    list(process_request(request_id))
    list(submit(request_id, "E002", "manager", "approve", "Looks good"))

    app = AppTest.from_file(str(APP_PATH)).run(timeout=20)
    assert not app.exception
    visible = "\n".join(element.value for element in app.markdown)
    assert app.title[0].value == "Decision Passport"
    headings = {item.value for item in app.subheader}
    assert "AI interpretation" in headings
    assert "SW-1.1" in visible
    assert "SW-1.2" in visible
    assert "Laya second opinion" in headings
    assert "Gateway and execution" in headings
    assert any("Audit chain: VERIFIED" in item.value for item in app.success)

    passport = app.button(key=f"verify_passport_{request_id}").click().run(timeout=20)
    assert not passport.exception
    assert any("Audit chain: VERIFIED" in item.value for item in passport.success)
    with db.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM tickets WHERE request_id=?", (request_id,)).fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM licenses WHERE request_id=?", (request_id,)).fetchone()[0] == 1