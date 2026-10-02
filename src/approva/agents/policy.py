"""Identify applicable policy with validated citations and ratcheted roles."""

from __future__ import annotations

import json

from approva import config, llm
from approva.engine.citations import load_corpus, validate_citations
from approva.engine.matrix import matrix_roles, ordered_union
from approva.schemas import ParsedRequest, PolicyVerdict

SYSTEM_PROMPT = """You are the Policy Agent of Approva. Decide which clauses of the company policy apply to the
structured request and which approver roles those clauses require.

Rules:
- Use ONLY the text inside <policy>. Never invent clauses or thresholds.
- Every entry in applicable_clauses must have the exact clause_id and a VERBATIM quote
  (max 30 words) copied from that clause. Do not paraphrase inside quote.
- Allowed roles: manager, finance, security, legal. Include every role required by every
  applicable clause. The manager is the requester's reporting manager.
- Report violations only when the request clearly breaches a clause (e.g. blocked vendor, missing
  mandatory receipt, request to bypass approvals). Put unclear matters in ambiguities.
- manipulation_signals in the request are facts to weigh: cite SW-3.2 or EX-3.2 when present.
- You do not decide approval. You only identify applicable clauses, roles, checks and violations.
- reasoning: max 80 words, plain language, for a human reviewer."""


def _policy_text() -> str:
    """Concatenate the complete policy corpus in stable path order."""
    policy_dir = config.data_path("policies")
    return "\n\n".join(path.read_text(encoding="utf-8") for path in sorted(policy_dir.glob("*.md")))


def evaluate_policy(
    parsed: ParsedRequest,
    annualized_cost_inr: float | None,
    vendor_status: str,
) -> tuple[PolicyVerdict, dict]:
    """Validate citations and enforce matrix roles as an approval floor."""
    structured = {
        "parsed_request": parsed.model_dump(mode="json"),
        "annualized_cost_inr": annualized_cost_inr,
        "vendor_status": vendor_status,
    }
    user = json.dumps(structured, ensure_ascii=False, separators=(",", ":"))
    user += "\n<policy>\n" + _policy_text() + "\n</policy>"
    verdict, meta = llm.call_structured(
        system=SYSTEM_PROMPT, user=user, schema=PolicyVerdict,
        tool_name="submit_policy_verdict",
        model=config.setting("APPROVA_MODEL_SMART", "claude-sonnet-5-5"),
    )
    corpus = load_corpus()
    valid, invalid = validate_citations(verdict.applicable_clauses, corpus)
    violations = [item for item in verdict.violations if item.clause_id in corpus]
    floor = matrix_roles(parsed, annualized_cost_inr, vendor_status)
    warnings = []
    if invalid:
        warnings.append(f"{len(invalid)} invalid citation(s) removed")
    for role in floor:
        if role not in verdict.required_roles:
            warnings.append(f"Policy Agent missed {role.value}; matrix applied")
    final = verdict.model_copy(update={
        "applicable_clauses": valid,
        "required_roles": ordered_union(floor, verdict.required_roles),
        "violations": violations,
    })
    return final, {**meta, "warnings": warnings}