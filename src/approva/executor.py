"""Executor-only entry point for guarded side-effect tools."""

from approva import db
from approva.tools.registry import call_tool


def create_manual_review_ticket(request_id: str, raw_text: str) -> str:
    """Route an unprocessable request to the Manual Review queue."""
    result = call_tool(
        "create_ticket", request_id=request_id, queue="Manual Review",
        title=f"Approva could not process request {request_id}", body=raw_text,
    )
    return result["ref_id"]


def run(request_id: str):
    """Run guarded workflow tools after authorization is implemented in P7."""
    raise NotImplementedError(f"Executor workflow for {request_id} is pending P7")