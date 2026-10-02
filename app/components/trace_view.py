"""Render stored and live trace events with policy and risk details."""

import json

import streamlit as st

from approva import db

STATUS_MARK = {"started": "◷", "ok": "✓", "warn": "!", "failed": "×"}


def request_events(request_id: str) -> list[dict]:
    """Return persisted audit event bodies for one request."""
    with db.connection() as conn:
        rows = conn.execute(
            "SELECT body_json FROM audit_events WHERE request_id=? ORDER BY seq", (request_id,)
        ).fetchall()
    return [json.loads(row["body_json"]) for row in rows]


def render_event(event: dict) -> None:
    """Render one trace event, including citations and risk factors when present."""
    marker = STATUS_MARK.get(event.get("status"), "•")
    latency = event.get("latency_ms")
    elapsed = f" · {latency} ms" if latency is not None else ""
    with st.container(border=True):
        st.markdown(f"**{marker} {event.get('agent', '').title()} · {event.get('status', '').upper()}**{elapsed}")
        st.write(event.get("summary", ""))
        detail = event.get("detail", {})
        result = detail.get("result", {})
        if event.get("agent") == "policy":
            for citation in result.get("applicable_clauses", []):
                st.markdown(f"> **{citation['clause_id']}** — “{citation['quote']}”")
        if event.get("agent") == "risk" and result:
            score = result.get("score", 0)
            st.progress(min(max(score, 0), 100), text=f"{result.get('tier', 'LOW')} risk · {score}/100")
            factors = result.get("factors", [])
            if factors:
                st.dataframe(factors, hide_index=True, width="stretch")
        with st.expander("Event details"):
            st.json(detail)


def render_request_trace(request_id: str) -> None:
    """Render every persisted event associated with a request."""
    for event in request_events(request_id):
        render_event(event)