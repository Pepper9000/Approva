"""Ordered deterministic decision policy and autonomy caps."""

from __future__ import annotations

from typing import Any

from approva.engine.matrix import load_matrix, matrix_roles, ordered_union
from approva.schemas import (
    Decision, DecisionType, ParsedRequest, PolicyVerdict, RequestType, RiskAssessment, Role,
)


def _context_value(ctx: Any, key: str, default: Any = None) -> Any:
    """Read a field from either mapping-style or object-style context."""
    return ctx.get(key, default) if isinstance(ctx, dict) else getattr(ctx, key, default)


def apply_autonomy_caps(decision: Decision, ctx: Any = None) -> Decision:
    """Cap auto-approval to manager review for degraded or Tier-2 contexts."""
    tier = _context_value(ctx, "tier", 1)
    if decision.type != DecisionType.AUTO_APPROVE or not (
        _context_value(ctx, "degraded", False) or tier >= 2
    ):
        return decision
    return decision.model_copy(update={
        "type": DecisionType.REQUIRE_APPROVAL,
        "required_roles": [Role.MANAGER],
        "rationale": [*decision.rationale, "Degraded mode: autonomy capped (Tier 2)"],
    })


def decide(
    parsed: ParsedRequest,
    verdict: PolicyVerdict,
    risk: RiskAssessment,
    annual_cost: float | None,
    vendor_status: str,
    cfg: dict | None = None,
    ctx: Any = None,
) -> Decision:
    """Apply the seven policy rules in precedence order, then autonomy caps."""
    cfg = cfg or load_matrix()
    floor = matrix_roles(parsed, annual_cost, vendor_status, cfg)
    roles = ordered_union(floor, verdict.required_roles)

    def result(kind: DecisionType, selected_roles=None, rationale: str = "", question=None) -> Decision:
        decision = Decision(
            type=kind, required_roles=selected_roles or [], rationale=[rationale],
            clarifying_question=question,
        )
        return apply_autonomy_caps(decision, ctx)

    if risk.hard_stops:
        return result(DecisionType.REJECT, rationale=f"Rule 1: {'; '.join(risk.hard_stops)}")
    if parsed.manipulation_signals:
        escalated_roles = ordered_union(floor, verdict.required_roles, [Role.SECURITY])
        return result(DecisionType.ESCALATE, escalated_roles, "Rule 2: manipulation signals require Security escalation")
    missing: list[str] = []
    if parsed.request_type == RequestType.UNKNOWN:
        missing.append("request_type")
    if parsed.unit_cost_inr is None:
        missing.append("unit_cost_inr")
    if parsed.request_type == RequestType.SOFTWARE and not parsed.vendor_or_payee:
        missing.append("vendor_or_payee")
    if parsed.request_type == RequestType.EXPENSE:
        if parsed.expense_category in (None, "other"):
            missing.append("expense_category")
        if parsed.expense_date is None:
            missing.append("expense_date")
    if missing:
        question = "Please provide: " + ", ".join(missing) + "."
        return result(DecisionType.NEEDS_INFO, rationale=f"Rule 3: critical fields missing ({', '.join(missing)})", question=question)
    if risk.tier == "HIGH" or verdict.violations:
        reason = f"Rule 4: risk score {risk.score} ({risk.tier})" if risk.tier == "HIGH" else "Rule 4: policy violation requires human review"
        return result(DecisionType.ESCALATE, roles, reason)
    if (
        parsed.request_type == RequestType.EXPENSE
        and annual_cost is not None
        and annual_cost > cfg["expense_claim"]["receipt_required_over_inr"]
        and parsed.receipt_attached is not True
    ):
        return result(DecisionType.NEEDS_INFO, roles, "Rule 5: receipt is required", "Please attach the expense receipt.")
    if not roles and risk.tier == "LOW":
        return result(DecisionType.AUTO_APPROVE, rationale="Rule 6: no approvers required and risk is LOW")
    return result(DecisionType.REQUIRE_APPROVAL, roles, "Rule 7: human approval is required")