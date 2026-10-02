"""Allowlisted tool registry used by the Executor."""

from dataclasses import dataclass
from typing import Callable

from approva.tools.ledger import post_ledger_entry, schedule_reimbursement
from approva.tools.licensing import provision_license
from approva.tools.notify import notify
from approva.tools.ticketing import create_ticket


@dataclass(frozen=True)
class Tool:
    """Describe a tool and the workflow types permitted to invoke it."""

    name: str
    fn: Callable[..., dict]
    side_effect: bool
    allowed_in: set[str]


REGISTRY = {
    tool.name: tool for tool in (
        Tool("create_ticket", create_ticket, True, {"software_license", "expense_claim", "unknown"}),
        Tool("provision_license", provision_license, True, {"software_license"}),
        Tool("post_ledger_entry", post_ledger_entry, True, {"expense_claim"}),
        Tool("schedule_reimbursement", schedule_reimbursement, True, {"expense_claim"}),
        Tool("notify", notify, True, {"software_license", "expense_claim", "unknown"}),
    )
}


def call_tool(name: str, authorization, request_type: str | None = None, **arguments) -> dict:
    """Dispatch a tool only with a gateway permit bound to this exact invocation."""
    tool = REGISTRY.get(name)
    if tool is None:
        raise ValueError(f"Tool is not registered: {name}")
    if request_type is not None and request_type not in tool.allowed_in:
        raise PermissionError(f"Tool {name} is not allowed for {request_type}")
    from approva.gateway import validate_permit

    if not validate_permit(authorization, name, arguments):
        raise PermissionError("Tool dispatch requires a matching ALLOW permit from the Decision Gateway")
    return tool.fn(authorization=authorization, **arguments)