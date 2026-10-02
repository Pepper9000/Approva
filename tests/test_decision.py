from datetime import date

from approva.engine.decision import decide
from approva.engine.risk import score_risk
from approva.schemas import DecisionType, ParsedRequest, PolicyVerdict, RequestType, Role


def test_scenario_d_manipulation_precedes_missing_information():
    parsed = ParsedRequest(
        request_type=RequestType.EXPENSE, summary="Urgent CFO payment", vendor_or_payee="Zenith Events",
        expense_category="other", unit_cost_inr=450_000, expense_date=date(2026, 10, 2),
        receipt_attached=False, manipulation_signals=["executive_name_drop", "skip_verification"],
        confidence=1,
    )
    verdict = PolicyVerdict(applicable_clauses=[], required_roles=[Role.MANAGER, Role.FINANCE], reasoning="")
    risk = score_risk(parsed, 450_000, "new", today=date(2026, 10, 2))
    decision = decide(parsed, verdict, risk, 450_000, "new")
    assert decision.type == DecisionType.ESCALATE
    assert decision.required_roles == [Role.MANAGER, Role.FINANCE, Role.SECURITY]


def test_scenario_b_auto_approves_but_degraded_caps_to_manager():
    parsed = ParsedRequest(
        request_type=RequestType.EXPENSE, summary="Cab fare", expense_category="local_conveyance",
        unit_cost_inr=1850, billing_period="one_time", expense_date=date(2026, 9, 28),
        receipt_attached=True, confidence=1,
    )
    verdict = PolicyVerdict(applicable_clauses=[], required_roles=[], reasoning="")
    risk = score_risk(parsed, 1850, "new", today=date(2026, 10, 2))
    assert risk.score == 0
    assert decide(parsed, verdict, risk, 1850, "new").type == DecisionType.AUTO_APPROVE
    capped = decide(parsed, verdict, risk, 1850, "new", ctx={"tier": 2, "degraded": True})
    assert capped.type == DecisionType.REQUIRE_APPROVAL
    assert capped.required_roles == [Role.MANAGER]


def test_hard_stop_rejects_before_other_rules():
    parsed = ParsedRequest(
        request_type=RequestType.SOFTWARE, summary="Blocked tool", vendor_or_payee="ShadyShare",
        unit_cost_inr=1000, confidence=1,
    )
    verdict = PolicyVerdict(applicable_clauses=[], required_roles=[], reasoning="")
    risk = score_risk(parsed, 1000, "blocked", today=date(2026, 10, 2))
    assert decide(parsed, verdict, risk, 1000, "blocked").type == DecisionType.REJECT


def test_unknown_request_needs_critical_information():
    parsed = ParsedRequest(request_type=RequestType.UNKNOWN, summary="Some purchase", confidence=0.4)
    verdict = PolicyVerdict(applicable_clauses=[], required_roles=[], reasoning="")
    risk = score_risk(parsed, None, "new", today=date(2026, 10, 2))
    result = decide(parsed, verdict, risk, None, "new")
    assert result.type == DecisionType.NEEDS_INFO
    assert "request_type" in result.clarifying_question
    assert "unit_cost_inr" in result.clarifying_question


def test_high_risk_escalates_and_missing_receipt_needs_info():
    verdict = PolicyVerdict(applicable_clauses=[], required_roles=[Role.MANAGER], reasoning="")
    high_risk = ParsedRequest(
        request_type=RequestType.SOFTWARE, summary="Expensive vendor", vendor_or_payee="NewCo",
        unit_cost_inr=4_000_000, data_categories=["customer_data"], confidence=1,
    )
    risk = score_risk(high_risk, 4_000_000, "new", today=date(2026, 10, 2))
    assert decide(high_risk, verdict, risk, 4_000_000, "new").type == DecisionType.ESCALATE

    expense = ParsedRequest(
        request_type=RequestType.EXPENSE, summary="Cab fare", expense_category="local_conveyance",
        unit_cost_inr=1850, expense_date=date(2026, 10, 1), receipt_attached=False, confidence=1,
    )
    expense_risk = score_risk(expense, 1850, "new", today=date(2026, 10, 2))
    result = decide(expense, verdict, expense_risk, 1850, "new")
    assert result.type == DecisionType.NEEDS_INFO
    assert result.clarifying_question == "Please attach the expense receipt."