"""Mock expense ledger and reimbursement tools."""

from datetime import datetime, timezone

from approva import db
from approva.gateway import AuthorizationResult, require_permit


def post_ledger_entry(
    request_id: str,
    payee: str,
    amount_inr: float,
    category: str,
    requester_id: str,
    authorization: AuthorizationResult,
) -> dict:
    """Post an approved expense claim to the mock ledger."""
    require_permit(authorization, "post_ledger_entry", {
        "request_id": request_id, "payee": payee, "amount_inr": amount_inr,
        "category": category, "requester_id": requester_id,
    })
    ledger_id = db.next_id("LED")
    with db.connection() as conn:
        conn.execute(
            "INSERT INTO ledger(id,kind,payee,amount_inr,category,requester_id,request_id,ts) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (ledger_id, "expense", payee, amount_inr, category, requester_id, request_id, datetime.now(timezone.utc).isoformat()),
        )
    return {"ref_id": ledger_id, "message": f"Posted ledger entry {ledger_id}"}


def schedule_reimbursement(
    request_id: str,
    payee: str,
    amount_inr: float,
    category: str,
    requester_id: str,
    authorization: AuthorizationResult,
) -> dict:
    """Record a mock reimbursement schedule in the ledger."""
    require_permit(authorization, "schedule_reimbursement", {
        "request_id": request_id, "payee": payee, "amount_inr": amount_inr,
        "category": category, "requester_id": requester_id,
    })
    schedule_id = db.next_id("LED")
    with db.connection() as conn:
        conn.execute(
            "INSERT INTO ledger(id,kind,payee,amount_inr,category,requester_id,request_id,ts) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (schedule_id, "reimbursement", payee, amount_inr, category, requester_id, request_id, datetime.now(timezone.utc).isoformat()),
        )
    return {"ref_id": schedule_id, "message": f"Scheduled reimbursement {schedule_id}"}