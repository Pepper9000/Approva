"""Deterministic derived-cost calculations."""

from approva.schemas import ParsedRequest

PERIOD_MULT = {"one_time": 1, "monthly": 12, "annual": 1}


def annualized_cost(parsed: ParsedRequest) -> float | None:
    """Return annualized INR cost, clamping a non-positive quantity to one."""
    if parsed.unit_cost_inr is None:
        return None
    return round(parsed.unit_cost_inr * max(parsed.quantity, 1) * PERIOD_MULT[parsed.billing_period], 2)