"""Deterministic approval roles and policy-clause mapping."""

from __future__ import annotations

from pathlib import Path

import yaml

from approva import config
from approva.schemas import DataCategory, ParsedRequest, RequestType, Role


def load_matrix(path: str | Path | None = None) -> dict:
    """Load the deterministic approval matrix from YAML."""
    matrix_path = Path(path) if path else config.data_path("approval_matrix.yaml")
    with matrix_path.open(encoding="utf-8") as matrix_file:
        return yaml.safe_load(matrix_file)


def ordered_union(*lists) -> list:
    """Return values in first-seen order with duplicates removed."""
    seen, result = set(), []
    for values in lists:
        for value in values:
            if value not in seen:
                seen.add(value)
                result.append(value)
    return result


def _tier(cfg: dict, key: str, amount: float) -> tuple[list[Role], int]:
    """Return the first matching tier's roles and one-based tier number."""
    for index, tier in enumerate(cfg, start=1):
        if tier[key] is None or amount <= tier[key]:
            return [Role(role) for role in tier["roles"]], index
    return [], len(cfg)


def matrix_roles_with_clauses(
    parsed: ParsedRequest,
    annual_cost: float | None,
    vendor_status: str,
    cfg: dict | None = None,
) -> tuple[list[Role], list[str]]:
    """Return deterministic minimum approvers and clauses implementing them."""
    cfg = cfg or load_matrix()
    amount = annual_cost if annual_cost is not None else 0
    roles: list[Role] = []
    clauses: list[str] = []
    if parsed.request_type == RequestType.SOFTWARE:
        rules = cfg["software_license"]
        roles, tier = _tier(rules["tiers"], "max_annual_inr", amount)
        clauses.append(["SW-1.2", "SW-1.3", "SW-1.4"][tier - 1])
        clauses.insert(0, "SW-1.1")
        if vendor_status == "blocked":
            clauses.append("SW-2.2")
        if vendor_status in ("unreviewed", "new"):
            roles += [Role(role) for role in rules["vendor_unreviewed_or_new_add"]]
            clauses.append("SW-2.1")
        new_vendor_rule = rules["new_vendor_over_inr"]
        if vendor_status == "new" and amount > new_vendor_rule["threshold"]:
            roles += [Role(role) for role in new_vendor_rule["add"]]
            clauses.append("SW-2.3")
        for category in parsed.data_categories:
            roles += [Role(role) for role in rules["data_rules"].get(category.value, [])]
            if category in (DataCategory.PII, DataCategory.CUSTOMER):
                clauses.append("DS-1.1")
            elif category in (DataCategory.FINANCIAL, DataCategory.HEALTH):
                clauses.append("DS-1.2")
            elif category == DataCategory.SOURCE_CODE:
                clauses.append("DS-1.3")
        request_text = f"{parsed.summary} {parsed.item or ''}".casefold()
        if DataCategory.CUSTOMER in parsed.data_categories and any(
            term in request_text for term in ("call", "record", "transcript")
        ):
            clauses.append("DS-2.1")
        if parsed.manipulation_signals:
            clauses.append("SW-3.2")
    elif parsed.request_type == RequestType.EXPENSE:
        rules = cfg["expense_claim"]
        roles, tier = _tier(rules["tiers"], "max_inr", amount)
        clauses.extend(("EX-1.1", f"EX-2.{tier}"))
        if amount > rules["receipt_required_over_inr"]:
            clauses.append("EX-1.2")
        if parsed.expense_date and (config.today() - parsed.expense_date).days > rules["filing_window_days"]:
            clauses.append("EX-1.3")
        unknown_rule = rules["unknown_payee_over_inr"]
        if vendor_status == "new" and amount > unknown_rule["threshold"]:
            roles += [Role(role) for role in unknown_rule["add"]]
            clauses.append("EX-3.1")
        if parsed.manipulation_signals:
            clauses.append("EX-3.2")
    return ordered_union(roles), ordered_union(clauses)


def matrix_roles(parsed: ParsedRequest, annual_cost: float | None, vendor_status: str, cfg: dict | None = None) -> list[Role]:
    """Return the deterministic approval floor without clause details."""
    return matrix_roles_with_clauses(parsed, annual_cost, vendor_status, cfg)[0]