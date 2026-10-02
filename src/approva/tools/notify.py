"""Mock notification outbox with an optional Slack webhook."""

from datetime import datetime, timezone

import requests

from approva import config, db


def notify(request_id: str, channel: str, recipient: str, subject: str, body: str) -> dict:
    """Write every notification to the outbox and optionally deliver to Slack."""
    delivered = 0
    warning = None
    webhook = config.setting("SLACK_WEBHOOK_URL").strip()
    if webhook:
        try:
            response = requests.post(webhook, json={"text": f"{subject}\n{body}"}, timeout=3)
            response.raise_for_status()
            delivered = 1
        except requests.RequestException as error:
            warning = f"Slack notification failed: {type(error).__name__}"
    with db.connection() as conn:
        conn.execute(
            "INSERT INTO outbox(channel,recipient,subject,body,delivered,request_id,ts) "
            "VALUES(?,?,?,?,?,?,?)",
            (channel, recipient, subject, body, delivered, request_id, datetime.now(timezone.utc).isoformat()),
        )
    return {"ref_id": None, "message": warning or "Notification recorded in outbox", "warning": bool(warning)}