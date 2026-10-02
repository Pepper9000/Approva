"""Create a short deterministic summary for human approvers."""

from approva.schemas import Decision, ParsedRequest, PolicyVerdict, RiskAssessment


def approver_summary(
    parsed: ParsedRequest,
    verdict: PolicyVerdict,
    risk: RiskAssessment,
    decision: Decision,
    annual_cost: float | None,
    vendor_status: str,
) -> str:
    """Return a four-line plain-text decision summary without another model call."""
    amount = "unknown" if annual_cost is None else f"INR {annual_cost:,.2f} annualized"
    factors = ", ".join(f"{factor.name} +{factor.points}" for factor in risk.factors if factor.points) or "no added factors"
    roles = ", ".join(role.value for role in decision.required_roles) or "none"
    clauses = ", ".join(citation.clause_id for citation in verdict.applicable_clauses) or "none"
    return "\n".join((
        f"Request: {parsed.summary}",
        f"Amount: {amount}; vendor status: {vendor_status}",
        f"Risk: {risk.tier} ({risk.score}); top factors: {factors}",
        f"Decision: {decision.type.value}; required approvers: {roles}; clauses: {clauses}",
    ))