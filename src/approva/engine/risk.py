"""Deterministic risk scoring and hard-stop detection."""

from __future__ import annotations

from datetime import date
from typing import Sequence

from approva import config
from approva.engine.matrix import load_matrix
from approva.schemas import DataCategory, ParsedRequest, RequestType, RiskAssessment, RiskFactor

AMOUNT_BANDS = [(50_000, 0), (200_000, 8), (500_000, 15), (2_500_000, 30), (float("inf"), 45)]
VENDOR_PTS = {"approved": 0, "unreviewed": 15, "new": 25}
DATA_PTS = {
    DataCategory.NONE: 0, DataCategory.INTERNAL: 5, DataCategory.SOURCE_CODE: 15,
    DataCategory.PII: 20, DataCategory.CUSTOMER: 20, DataCategory.FINANCIAL: 30,
    DataCategory.HEALTH: 30,
}


def score_risk(
    parsed: ParsedRequest,
    annual_cost: float | None,
    vendor_status: str,
    today: date | None = None,
    cfg: dict | None = None,
    extra_factors: Sequence[RiskFactor] = (),
) -> RiskAssessment:
    """Compute policy-defined risk points and hard stops without model input."""
    cfg = cfg or load_matrix()
    today = today or config.today()
    amount = annual_cost if annual_cost is not None else 0
    factors: list[RiskFactor] = []
    hard_stops: list[str] = []
    amount_points = next(points for limit, points in AMOUNT_BANDS if amount <= limit)
    factors.append(RiskFactor(name="amount", points=amount_points, detail=f"Annualised cost INR {amount:,.0f}"))
    apply_vendor = parsed.request_type == RequestType.SOFTWARE or amount > 100_000
    if vendor_status == "blocked":
        hard_stops.append("Vendor is on the Blocked Vendor list (SW-2.2)")
    elif apply_vendor:
        factors.append(RiskFactor(
            name="vendor", points=VENDOR_PTS.get(vendor_status, 25), detail=f"Vendor status: {vendor_status}"
        ))
    data_points = max((DATA_PTS[category] for category in parsed.data_categories), default=0)
    factors.append(RiskFactor(
        name="data_sensitivity", points=data_points,
        detail=", ".join(category.value for category in parsed.data_categories),
    ))
    if parsed.manipulation_signals:
        factors.append(RiskFactor(
            name="manipulation", points=20, detail=", ".join(parsed.manipulation_signals)
        ))
    if parsed.request_type == RequestType.EXPENSE and parsed.expense_date:
        window = cfg["expense_claim"]["filing_window_days"]
        if (today - parsed.expense_date).days > window:
            hard_stops.append(f"Claim filed outside the {window}-day window (EX-1.3)")
    factors.extend(extra_factors)
    score = min(100, sum(factor.points for factor in factors))
    tier = "LOW" if score < 25 else "MEDIUM" if score < 50 else "HIGH"
    return RiskAssessment(score=score, tier=tier, factors=factors, hard_stops=hard_stops)