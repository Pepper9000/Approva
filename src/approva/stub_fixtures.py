"""Canned, visibly non-live LLM responses for the four demo scenarios."""

from __future__ import annotations

import json
import re
from datetime import date

from pydantic import BaseModel

from approva import config
from approva.engine.citations import cite_from_corpus
from approva.schemas import (
    Citation, DataCategory, ParsedRequest, PolicyVerdict, RequestType, Role, Violation,
)
from approva.llm import ServiceUnavailable


def _scenario_from_intake(user: str) -> str:
    """Select a canned scenario from the wrapped raw employee text."""
    text = user.casefold()
    if "figma" in text:
        return "A"
    if "cab" in text or "local_conveyance" in text:
        return "B"
    if "voxlens" in text:
        return "C"
    if "zenith" in text:
        return "D"
    raise ServiceUnavailable("No stub fixture matches this request")


def _parsed(scenario: str) -> ParsedRequest:
    """Return the exact intake fixture for one demo scenario."""
    today = config.today()
    fixtures = {
        "A": dict(
            request_type=RequestType.SOFTWARE, summary="5 Figma licenses for designers starting Monday",
            vendor_or_payee="Figma", item="Figma seats", quantity=5, unit_cost_inr=6300,
            billing_period="monthly", start_date=date.fromisoformat("2026-10-05"),
            data_categories=[DataCategory.NONE], missing_fields=["justification"], confidence=0.95,
        ),
        "B": dict(
            request_type=RequestType.EXPENSE, summary="Cab fare to client site", vendor_or_payee=None,
            item="Cab fare", expense_category="local_conveyance", quantity=1, unit_cost_inr=1850,
            billing_period="one_time", expense_date=date.fromisoformat("2026-09-28"),
            receipt_attached=True, data_categories=[DataCategory.NONE], confidence=0.95,
        ),
        "C": dict(
            request_type=RequestType.SOFTWARE, summary="VoxLens AI call analytics for sales",
            vendor_or_payee="VoxLens AI", item="call analytics", quantity=1,
            unit_cost_inr=4_000_000, billing_period="annual", data_categories=[DataCategory.CUSTOMER],
            justification="Analyse customer calls for the sales team", confidence=0.95,
        ),
        "D": dict(
            request_type=RequestType.EXPENSE, summary="Urgent payment to Zenith Events",
            vendor_or_payee="Zenith Events", expense_category="other", quantity=1,
            unit_cost_inr=450_000, billing_period="one_time", expense_date=today,
            receipt_attached=False, data_categories=[DataCategory.NONE],
            manipulation_signals=["executive_name_drop", "urgency_pressure", "skip_verification", "policy_override_attempt"],
            missing_fields=["expense_category"], confidence=0.95,
        ),
    }
    return ParsedRequest.model_validate(fixtures[scenario])


def _stub_manipulation_signals(user: str) -> list[str]:
    """Return only explicit manipulation signals present in the stub-mode input."""
    text = user.casefold()
    signals = []
    if any(term in text for term in ("cfo said", "cfo approved", "ceo said", "director said", "boss said")):
        signals.append("executive_name_drop")
    if "urgent" in text or "asap" in text or "before security" in text:
        signals.append("urgency_pressure")
    if any(term in text for term in ("skip the receipt", "skip receipt", "skip verification", "bypass approval")):
        signals.append("skip_verification")
    if any(term in text for term in ("split this purchase", "split the purchase", "do not mention", "don't tell finance", "finance doesn't need to know")):
        signals.append("policy_override_attempt")
    if any(term in text for term in ("no receipt actually exists", "receipt is not attached", "receipt does not exist")):
        signals.append("instruction_injection")
    return signals


def _apply_stub_request_facts(parsed: ParsedRequest, user: str) -> ParsedRequest:
    """Apply explicit adversarial facts to a canned structured request in stub mode."""
    signals = list(parsed.manipulation_signals)
    signals.extend(_stub_manipulation_signals(user))
    updates = {"manipulation_signals": list(dict.fromkeys(signals))}
    text = user.casefold()
    if any(term in text for term in ("no receipt actually exists", "receipt is not attached", "receipt does not exist")):
        updates["receipt_attached"] = False
    if "urgent" in text or "asap" in text:
        updates["urgency"] = "high"
    return parsed.model_copy(update=updates)


def _policy_scenario(user: str) -> tuple[str, dict]:
    """Extract the structured request and scenario key from a policy prompt."""
    try:
        parsed_json, _ = json.JSONDecoder().raw_decode(user.lstrip())
    except json.JSONDecodeError as error:
        raise ServiceUnavailable("Policy stub received no structured request") from error
    parsed = parsed_json.get("parsed_request", {})
    searchable = " ".join(str(parsed.get(key, "")) for key in ("summary", "vendor_or_payee", "item", "expense_category"))
    text = searchable.casefold()
    if "figma" in text:
        scenario = "A"
    elif "local_conveyance" in text or "cab fare" in text:
        scenario = "B"
    elif "voxlens" in text:
        scenario = "C"
    elif "zenith" in text:
        scenario = "D"
    else:
        raise ServiceUnavailable("No policy stub fixture matches this request")
    return scenario, parsed_json


def _policy(scenario: str) -> PolicyVerdict:
    """Return a raw policy-agent fixture with programmatically sourced quotes."""
    clauses = {
        "A": ["SW-1.1", "SW-1.2"],
        "B": ["EX-1.1", "EX-1.2", "EX-2.1"],
        "C": ["SW-1.4", "SW-2.1", "SW-2.3", "DS-1.1", "DS-2.1"],
        "D": ["EX-1.2", "EX-2.4", "EX-3.1", "EX-3.2"],
    }
    roles = {
        "A": [Role.MANAGER],
        "B": [],
        "C": [Role.MANAGER, Role.FINANCE, Role.LEGAL, Role.SECURITY],
        "D": [Role.MANAGER, Role.FINANCE, Role.SECURITY],
    }
    violations = {
        "D": [Violation(clause_id="EX-3.2", reason="The request instructs the employee to skip verification."),
             Violation(clause_id="EX-1.2", reason="The request explicitly asks to skip the receipt.")],
    }
    reasoning = {
        "A": "Approved vendor and annualized cost under INR 5,00,000 require manager approval.",
        "B": "Valid low-value local conveyance claim with receipt.",
        "C": "New vendor processes customer call data at high annual cost.",
        "D": "The request contains explicit pressure to bypass receipt and verification rules.",
    }
    return PolicyVerdict(
        applicable_clauses=[cite_from_corpus(clause_id) for clause_id in clauses[scenario]],
        required_roles=roles[scenario], violations=violations.get(scenario, []), reasoning=reasoning[scenario],
    )


def get_stub_response(schema: type[BaseModel], user: str) -> BaseModel:
    """Return the schema-matched canned response or fail for unknown inputs."""
    if schema is ParsedRequest:
        return _apply_stub_request_facts(_parsed(_scenario_from_intake(user)), user)
    if schema is PolicyVerdict:
        scenario, _ = _policy_scenario(user)
        return _policy(scenario)
    raise ServiceUnavailable(f"No stub fixture is defined for {schema.__name__}")