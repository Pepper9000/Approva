"""Run structured Laya checks and apply tighten-only results."""

from __future__ import annotations

from typing import Any

from approva import config
from approva.engine.matrix import ordered_union
from approva.laya.client import LayaClientProtocol, LayaUnavailable, get_laya_client
from approva.schemas import DataCategory, ParsedRequest, RequestType, Role

DATA_SENSITIVITY_ORDER = {
    DataCategory.NONE.value: 0,
    DataCategory.INTERNAL.value: 1,
    DataCategory.SOURCE_CODE.value: 2,
    DataCategory.PII.value: 3,
    DataCategory.CUSTOMER.value: 3,
    DataCategory.FINANCIAL.value: 4,
    DataCategory.HEALTH.value: 4,
}
SCRUTINY_ROLES = {
    "none": [],
    "manager": [Role.MANAGER],
    "finance": [Role.FINANCE],
    "security": [Role.SECURITY],
    "legal": [Role.LEGAL],
    "security_and_legal": [Role.SECURITY, Role.LEGAL],
    "finance_and_security": [Role.FINANCE, Role.SECURITY],
}


def _structured_state(parsed: ParsedRequest, annual_cost: float | None) -> dict[str, Any]:
    """Build Laya input from typed fields without forwarding raw employee text."""
    return {
        "request_type": parsed.request_type.value,
        "summary": parsed.summary,
        "vendor": parsed.vendor_or_payee,
        "item": parsed.item,
        "expense_category": parsed.expense_category,
        "annualized_cost_inr": annual_cost,
        "quantity": parsed.quantity,
        "unit_cost_inr": parsed.unit_cost_inr,
        "billing_period": parsed.billing_period,
        "data_categories": [category.value for category in parsed.data_categories],
        "receipt_attached": parsed.receipt_attached,
        "manipulation_signals": list(parsed.manipulation_signals),
        "justification": parsed.justification,
    }


def _questions(parsed: ParsedRequest) -> dict:
    """Build small, closed-choice questions supported by Laya's card."""
    questions = {
        "request_type": {
            "type": "choice",
            "instructions": "Which workflow best matches this structured request?",
            "criteria": {
                RequestType.SOFTWARE.value: "Purchase or subscription for software licenses",
                RequestType.EXPENSE.value: "Reimbursement or expense claim",
                RequestType.UNKNOWN.value: "Neither supported workflow or insufficient evidence",
            },
        },
        "data_sensitivity": {
            "type": "choice",
            "instructions": "What is the most sensitive data category indicated?",
            "criteria": {category.value: category.value.replace("_", " ") for category in DataCategory},
        },
        "receipt_attached": {
            "type": "choice",
            "instructions": "Does the structured request confirm a receipt is attached?",
            "criteria": {
                "yes": "The request says a receipt is attached or available",
                "no": "The request says no receipt is attached or asks to skip it",
                "unknown": "The structured request does not establish receipt state",
            },
        },
        "manipulation": {
            "type": "choice",
            "instructions": "Does the structured request indicate pressure or an attempt to bypass controls?",
            "criteria": {
                "A": "No authority spoofing, urgency pressure, concealment, false evidence, or control bypass",
                "B": "Authority spoofing, urgency pressure, concealment, false evidence, or control bypass is indicated",
            },
        },
        "additional_scrutiny": {
            "type": "choice",
            "instructions": "What additional human review, if any, should be considered?",
            "criteria": {name: name.replace("_", " ") for name in SCRUTINY_ROLES},
        },
    }
    if parsed.request_type == RequestType.EXPENSE:
        questions["expense_category"] = {
            "type": "choice",
            "instructions": "Which expense category best matches the structured request?",
            "criteria": {
                "travel": "Travel or transport",
                "accommodation": "Hotel or lodging",
                "meals": "Meals while travelling",
                "local_conveyance": "Local cab or conveyance",
                "training": "Training or conference",
                "office_supplies": "Office supplies",
                "other": "Other expense or insufficient evidence",
            },
        }
    return questions


def _choice(answers: dict, key: str, allowed: set[str]) -> tuple[str | None, float | None]:
    """Read a documented choice answer and optional model-reported confidence."""
    answer = answers.get(key)
    if not isinstance(answer, dict):
        return None, None
    value = answer.get("choice")
    confidence = answer.get("confidence")
    confidence = confidence if isinstance(confidence, (int, float)) else None
    return (value if isinstance(value, str) and value in allowed else None), confidence


def _keyword_fallback(parsed: ParsedRequest, state: dict) -> dict:
    """Return a conservative local second opinion from structured fields only."""
    text = " ".join(str(state.get(field) or "") for field in ("summary", "item", "justification")).casefold()
    manipulation = bool(parsed.manipulation_signals) or any(term in text for term in (
        "cfo said", "ceo said", "skip", "bypass", "just approve", "urgent", "do not mention",
        "don't tell", "split this purchase", "receipt is attached",
    ))
    current_data = max(parsed.data_categories, key=lambda item: DATA_SENSITIVITY_ORDER[item.value]).value
    return {
        "request_type": parsed.request_type.value,
        "expense_category": parsed.expense_category,
        "data_sensitivity": current_data,
        "receipt_attached": "no" if parsed.receipt_attached is False else "unknown",
        "manipulation": "B" if manipulation else "A",
        "additional_scrutiny": "security" if manipulation else "none",
    }


def merge_required_roles(matrix_roles: list[Role], policy_roles: list[Role], laya_roles: list[Role]) -> list[Role]:
    """Ratchet all approval sources together without permitting role removal."""
    return ordered_union(matrix_roles, policy_roles, laya_roles)


def crosscheck(
    parsed: ParsedRequest,
    annual_cost: float | None,
    *,
    mode: str | None = None,
    client: LayaClientProtocol | None = None,
) -> tuple[ParsedRequest, dict]:
    """Return a parsed request tightened only by an explicitly enabled Laya gate."""
    mode = (mode or config.laya_mode()).lower()
    if mode not in {"off", "log_only", "gate"}:
        raise ValueError(f"Unsupported LAYA_MODE: {mode}")
    state = _structured_state(parsed, annual_cost)
    if mode == "off":
        return parsed, {
            "mode": mode, "status": "SKIPPED", "source": "none", "answers": {},
            "added_roles": [], "block_auto": False, "recommendations": [],
        }

    source = "laya"
    unavailable_reason = None
    try:
        client = client or get_laya_client(config.setting(
            "LAYA_CHECKPOINT", "convaiinnovations/laya-typed-decisions"
        ))
        if not client.ready():
            raise LayaUnavailable("Laya package or checkpoint unavailable")
        result = client.predict(state, _questions(parsed))
        answers = result.get("answers") if isinstance(result, dict) else None
        if not isinstance(answers, dict) or not answers:
            raise LayaUnavailable("Laya returned no typed answers")
    except Exception as error:
        source = "keyword_fallback"
        unavailable_reason = f"{type(error).__name__}: {error}"
        answers = _keyword_fallback(parsed, state)
        status = "UNAVAILABLE"

    if source == "keyword_fallback":
        choices = answers
        confidence = {}
        parsed_answers = {key: {"choice": value} for key, value in answers.items()}
    else:
        parsed_answers = {key: value for key, value in answers.items() if isinstance(value, dict)}
        allowed = {
            "request_type": {value.value for value in RequestType},
            "data_sensitivity": {value.value for value in DataCategory},
            "receipt_attached": {"yes", "no", "unknown"},
            "manipulation": {"A", "B"},
            "additional_scrutiny": set(SCRUTINY_ROLES),
            "expense_category": {"travel", "accommodation", "meals", "local_conveyance", "training", "office_supplies", "other"},
        }
        choices, confidence = {}, {}
        for key, valid_values in allowed.items():
            value, reported_confidence = _choice(answers, key, valid_values)
            choices[key] = value
            if reported_confidence is not None:
                confidence[key] = reported_confidence
    recommendations: list[str] = []
    added_roles: list[Role] = []
    block_auto = mode == "gate" and source != "laya"
    if source == "keyword_fallback" and block_auto:
        recommendations.append("Laya unavailable; local fallback blocks autonomous approval")
    if choices.get("request_type") and choices["request_type"] != parsed.request_type.value:
        recommendations.append("workflow disagreement")
        if mode == "gate":
            block_auto = True
    if parsed.request_type == RequestType.EXPENSE and choices.get("expense_category"):
        if choices["expense_category"] != parsed.expense_category:
            recommendations.append("expense category disagreement")
            if mode == "gate":
                block_auto = True
    predicted_data = choices.get("data_sensitivity")
    if predicted_data in DATA_SENSITIVITY_ORDER:
        current_level = max(DATA_SENSITIVITY_ORDER[item.value] for item in parsed.data_categories)
        if DATA_SENSITIVITY_ORDER[predicted_data] > current_level:
            recommendations.append(f"data sensitivity raised to {predicted_data}")
    if choices.get("manipulation") == "B" and not parsed.manipulation_signals:
        recommendations.append("possible manipulation detected")
    if choices.get("receipt_attached") == "no" and parsed.receipt_attached is not False:
        recommendations.append("receipt state tightened to absent")
    scrutiny = choices.get("additional_scrutiny")
    if scrutiny in SCRUTINY_ROLES:
        added_roles = SCRUTINY_ROLES[scrutiny]
        if added_roles:
            recommendations.append("additional scrutiny: " + ", ".join(role.value for role in added_roles))

    updated = parsed
    applied: list[str] = []
    gate_status = "AGREED"
    if mode == "gate":
        categories = list(parsed.data_categories)
        if predicted_data in DATA_SENSITIVITY_ORDER and (
            DATA_SENSITIVITY_ORDER[predicted_data]
            > max(DATA_SENSITIVITY_ORDER[item.value] for item in categories)
        ):
            categories = ordered_union(categories, [DataCategory(predicted_data)])
            applied.append(f"data sensitivity raised to {predicted_data}")
        if choices.get("manipulation") == "B" and not parsed.manipulation_signals:
            updated = updated.model_copy(update={
                "manipulation_signals": [*updated.manipulation_signals, "instruction_injection"],
            })
            applied.append("manipulation signal added")
        if choices.get("receipt_attached") == "no" and parsed.receipt_attached is not False:
            updated = updated.model_copy(update={"receipt_attached": False})
            applied.append("receipt state tightened to absent")
        if categories != parsed.data_categories:
            updated = updated.model_copy(update={"data_categories": categories})
        added_roles = ordered_union([], added_roles)
        gate_status = "TIGHTENED" if applied or added_roles or block_auto else "AGREED"
        status = "UNAVAILABLE" if source == "keyword_fallback" else gate_status
    elif source == "laya":
        status = "OBSERVED_STRICTER" if recommendations else "AGREED"
        added_roles = []
    result_json = {
        "mode": mode,
        "status": status,
        "source": source,
        "answers": parsed_answers,
        "confidence": confidence,
        "recommendations": recommendations,
        "applied": applied,
        "added_roles": [role.value for role in added_roles] if mode == "gate" else [],
        "block_auto": block_auto if mode == "gate" else False,
    }
    if unavailable_reason:
        result_json["unavailable_reason"] = unavailable_reason
        result_json["fallback_status"] = gate_status if mode == "gate" else "OBSERVED"
    return updated, result_json