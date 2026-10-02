"""Minimal allowlist registry for executor-only tool calls."""

from approva.tools.ticketing import create_ticket

REGISTRY = {"create_ticket": create_ticket}


def call_tool(name: str, **arguments) -> dict:
    """Invoke an allowlisted tool by name."""
    tool = REGISTRY.get(name)
    if tool is None:
        raise ValueError(f"Tool is not registered: {name}")
    return tool(**arguments)