import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from approva import db
from approva.orchestrator import create_request, process_request

APP_ROOT = Path(__file__).resolve().parents[1] / "app"
SCENARIO_A = "Need Figma licenses for 5 designers, ~₹6,300/seat/month, starting Monday."


@pytest.mark.parametrize("page", [APP_ROOT / "Home.py", APP_ROOT / "pages" / "1_Submit.py", APP_ROOT / "pages" / "2_Approvals.py"])
def test_each_app_page_loads_without_exception(monkeypatch, tmp_path, page):
    monkeypatch.setenv("LLM_MODE", "stub")
    monkeypatch.setenv("APPROVA_DB", str(tmp_path / f"{page.stem}.db"))
    app = AppTest.from_file(str(page)).run(timeout=15)
    assert not app.exception
    assert any("LLM mode: STUB" in caption.value for caption in app.caption)
    assert any("STUB MODE: canned AI responses, not live" in warning.value for warning in app.warning)


def test_submit_scenario_a_renders_trace_citations_risk_and_result(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_MODE", "stub")
    monkeypatch.setenv("APPROVA_DB", str(tmp_path / "submit.db"))
    db.seed_from_yaml()
    app = AppTest.from_file(str(APP_ROOT / "pages" / "1_Submit.py")).run(timeout=15)
    app.text_area(key="request_text").set_value(SCENARIO_A)
    app.button(key="submit_request").click().run(timeout=30)

    assert not app.exception
    visible = "\n".join(element.value for element in app.markdown)
    assert "REQUIRE_APPROVAL" in visible
    assert "SW-1.1" in visible
    assert "Risk score 15 (LOW)" in visible
    assert db.get_request(app.session_state["last_request_id"])["status"] == "AWAITING_APPROVAL"


def test_approvals_page_completes_scenario_a_as_manager(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_MODE", "stub")
    monkeypatch.setenv("APPROVA_DB", str(tmp_path / "approvals-ui.db"))
    db.seed_from_yaml()
    request_id = create_request("E001", SCENARIO_A)
    list(process_request(request_id))

    app = AppTest.from_file(str(APP_ROOT / "pages" / "2_Approvals.py")).run(timeout=15)
    app.selectbox(key="acting_as").select("E002").run(timeout=15)
    app.button(key=f"approve_{request_id}_manager").click().run(timeout=30)

    assert not app.exception
    assert db.get_request(request_id)["status"] == "COMPLETED"
    assert any("Execution completed" in item.value for item in app.success)
    visible = "\n".join(element.value for element in app.markdown)
    assert "Execution guard passed" in visible
    assert "Provisioned 5 seats" in visible
    with db.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM licenses WHERE request_id=?", (request_id,)).fetchone()[0] == 1