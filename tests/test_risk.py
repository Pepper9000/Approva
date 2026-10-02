from datetime import date

import pytest

from approva.engine.risk import score_risk
from approva.schemas import ParsedRequest, RiskFactor


@pytest.mark.parametrize(("amount", "expected"), [(50_000, 0), (50_001, 8), (200_000, 8), (200_001, 15), (500_000, 15), (500_001, 30), (2_500_000, 30), (2_500_001, 45)])
def test_amount_band_edges(amount, expected):
    parsed = ParsedRequest(request_type="expense_claim", summary="Expense", confidence=1)
    risk = score_risk(parsed, amount, "new", today=date(2026, 10, 2))
    assert risk.factors[0].points == expected


@pytest.mark.parametrize(("score", "tier"), [(24, "LOW"), (25, "MEDIUM"), (49, "MEDIUM"), (50, "HIGH")])
def test_risk_tier_thresholds(score, tier):
    parsed = ParsedRequest(request_type="unknown", summary="Unknown", confidence=1)
    risk = score_risk(
        parsed, 0, "new", today=date(2026, 10, 2),
        extra_factors=[RiskFactor(name="boundary", points=score, detail="boundary test")],
    )
    assert risk.score == score
    assert risk.tier == tier


def test_scenario_c_and_blocked_vendor_hard_stop():
    parsed = ParsedRequest(
        request_type="software_license", summary="Call recordings", unit_cost_inr=4_000_000,
        billing_period="annual", data_categories=["customer_data"], confidence=1,
    )
    risk = score_risk(parsed, 4_000_000, "new", today=date(2026, 10, 2))
    assert risk.score == 90
    assert risk.tier == "HIGH"
    assert score_risk(parsed, 4_000_000, "blocked", today=date(2026, 10, 2)).hard_stops