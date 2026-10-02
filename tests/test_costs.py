from approva.engine.costs import annualized_cost
from approva.schemas import ParsedRequest, RequestType


def test_annualized_cost_uses_period_and_quantity():
    parsed = ParsedRequest(
        request_type=RequestType.SOFTWARE,
        summary="Seats",
        quantity=5,
        unit_cost_inr=6300,
        billing_period="monthly",
        confidence=1,
    )
    assert annualized_cost(parsed) == 378000


def test_annualized_cost_missing_value_and_nonpositive_quantity():
    missing = ParsedRequest(request_type="unknown", summary="Unknown", confidence=0.5)
    zero_quantity = ParsedRequest(
        request_type="software_license", summary="One", quantity=0,
        unit_cost_inr=100, billing_period="annual", confidence=1,
    )
    assert annualized_cost(missing) is None
    assert annualized_cost(zero_quantity) == 100