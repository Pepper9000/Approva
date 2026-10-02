from approva.engine.matrix import matrix_roles_with_clauses
from approva.schemas import DataCategory, ParsedRequest, RequestType, Role


def test_software_new_vendor_and_customer_data_add_roles_and_clauses():
    parsed = ParsedRequest(
        request_type=RequestType.SOFTWARE, summary="Customer call recordings",
        item="call analytics", vendor_or_payee="VoxLens AI", unit_cost_inr=4_000_000,
        billing_period="annual", data_categories=[DataCategory.CUSTOMER], confidence=1,
    )
    roles, clauses = matrix_roles_with_clauses(parsed, 4_000_000, "new")
    assert roles == [Role.MANAGER, Role.FINANCE, Role.LEGAL, Role.SECURITY]
    assert clauses == ["SW-1.1", "SW-1.4", "SW-2.1", "SW-2.3", "DS-1.1", "DS-2.1"]


def test_expense_tier_and_receipt_clause():
    parsed = ParsedRequest(
        request_type=RequestType.EXPENSE, summary="Cab", expense_category="local_conveyance",
        unit_cost_inr=18_500, billing_period="one_time", receipt_attached=True, confidence=1,
    )
    roles, clauses = matrix_roles_with_clauses(parsed, 18_500, "new")
    assert roles == [Role.MANAGER]
    assert clauses == ["EX-1.1", "EX-2.2", "EX-1.2"]