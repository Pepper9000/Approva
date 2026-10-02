"""Mock software-license provisioning tool."""

from approva import db


def provision_license(
    request_id: str,
    vendor: str,
    item: str,
    seats: int,
    requester_id: str,
    start_date: str | None,
) -> dict:
    """Create a license row and return its reference ID."""
    license_id = db.next_id("LIC")
    with db.connection() as conn:
        conn.execute(
            "INSERT INTO licenses(id,vendor,item,seats,requester_id,start_date,request_id) "
            "VALUES(?,?,?,?,?,?,?)",
            (license_id, vendor, item, seats, requester_id, start_date, request_id),
        )
    return {"ref_id": license_id, "message": f"Provisioned {seats} seats as {license_id}"}