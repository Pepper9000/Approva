"""Mock ticket creation tool."""

from datetime import datetime, timezone

from approva import db


def create_ticket(request_id: str, queue: str, title: str, body: str) -> dict:
    """Create a ticket row and return its reference ID."""
    ticket_id = db.next_id("TKT")
    with db.connection() as conn:
        conn.execute(
            "INSERT INTO tickets(id,queue,title,body,status,request_id,ts) VALUES(?,?,?,?,?,?,?)",
            (ticket_id, queue, title, body, "OPEN", request_id, datetime.now(timezone.utc).isoformat()),
        )
    return {"ref_id": ticket_id, "message": f"Created {queue} ticket {ticket_id}"}