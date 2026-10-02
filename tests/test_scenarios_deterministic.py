from datetime import date

import pytest

from approva.engine.costs import annualized_cost
from approva.engine.decision import decide
from approva.engine.matrix import matrix_roles
from approva.engine.risk import score_risk
from approva.schemas import DataCategory, DecisionType, ParsedRequest, PolicyVerdict, Role


@pytest.mark.parametrize(
    ("parsed", "status", "expected", "roles", "score"),
    [
        (ParsedRequest(request_type="software_license", summary="Figma", vendor_or_payee="Figma", quantity=5, unit_cost_inr=6300, billing_period="monthly", confidence=1), "approved", DecisionType.REQUIRE_APPROVAL, [Role.MANAGER], 15),
        (ParsedRequest(request_type="expense_claim", summary="Cab", expense_category="local_conveyance", unit_cost_inr=1850, expense_date=date(2026, 9, 28), receipt_attached=True, confidence=1), "new", DecisionType.AUTO_APPROVE, [], 0),
        (ParsedRequest(request_type="software_license", summary="Customer call recordings", vendor_or_payee="VoxLens AI", unit_cost_inr=4_000_000, billing_period="annual", data_categories=[DataCategory.CUSTOMER], confidence=1), "new", DecisionType.ESCALATE, [Role.MANAGER, Role.FINANCE, Role.LEGAL, Role.SECURITY], 90),
        (ParsedRequest(request_type="expense_claim", summary="CFO urgent payment", vendor_or_payee="Zenith Events", expense_category="other", unit_cost_inr=450_000, expense_date=date(2026, 10, 2), receipt_attached=False, manipulation_signals=["executive_name_drop", "urgency_pressure", "skip_verification", "policy_override_attempt"], confidence=1), "new", DecisionType.ESCALATE, [Role.MANAGER, Role.FINANCE, Role.SECURITY], 60),
    ],
)
def test_hand_built_scenarios_match_decisions(parsed, status, expected, roles, score):
    cost = annualized_cost(parsed)
    floor = matrix_roles(parsed, cost, status)
    verdict = PolicyVerdict(applicable_clauses=[], required_roles=floor, reasoning="")
    risk = score_risk(parsed, cost, status, today=date(2026, 10, 2))
    assert risk.score == score
    result = decide(parsed, verdict, risk, cost, status)
    assert result.type == expected
    assert result.required_roles == roles