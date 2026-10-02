import json

import streamlit as st

from app.components.sidebar import render_sidebar
from app.components.trace_view import render_event
from approva import db
from approva.approvals import submit

st.set_page_config(page_title="Approvals · Approva", layout="wide")
acting_as = render_sidebar()
st.title("Approvals")

with db.connection() as conn:
    pending = conn.execute(
        "SELECT * FROM requests WHERE status=? ORDER BY created_at",
        ("AWAITING_APPROVAL",),
    ).fetchall()
    actor = conn.execute("SELECT * FROM employees WHERE id=?", (acting_as,)).fetchone()

visible = []
if actor:
    for row in pending:
        request = dict(row)
        decision = json.loads(request.get("decision_json") or "{}")
        with db.connection() as conn:
            requester = conn.execute("SELECT manager_id FROM employees WHERE id=?", (request["requester_id"],)).fetchone()
        role = "manager" if actor["role"] == "manager" and requester and requester["manager_id"] == acting_as else actor["role"]
        if role in decision.get("required_roles", []):
            visible.append((request, decision, role))

if not visible:
    st.info("No requests are waiting for your approval.")

for request, decision, role in visible:
    request_id = request["id"]
    parsed = json.loads(request.get("parsed_json") or "{}")
    policy = json.loads(request.get("policy_json") or "{}")
    risk = json.loads(request.get("risk_json") or "{}")
    summary = json.loads(request.get("brief_json") or '""')
    approvals = db.get_approvals(request_id)
    approved_roles = {item["role"] for item in approvals if item["verdict"] == "approve"}
    with st.container(border=True):
        st.subheader(parsed.get("summary", request.get("raw_text", request_id)))
        st.caption(f"Requester {request['requester_id']} · {request.get('vendor_status', 'unknown')} vendor · "
                   f"INR {request.get('annual_cost') or 0:,.2f} annualized")
        if risk:
            st.progress(min(max(risk.get("score", 0), 0), 100), text=f"{risk.get('tier')} risk · {risk.get('score')}/100")
            st.dataframe(risk.get("factors", []), hide_index=True, width="stretch")
        for citation in policy.get("applicable_clauses", []):
            st.markdown(f"> **{citation['clause_id']}** — “{citation['quote']}”")
        if summary:
            st.text(summary)
        progress = " · ".join(
            f"{'✓' if required in approved_roles else '◷'} {required.title()}"
            for required in decision.get("required_roles", [])
        )
        st.caption(progress)
        comment = st.text_input("Comment", key=f"comment_{request_id}_{role}")
        approve_col, reject_col = st.columns(2)
        for label, verdict, column in (
            ("Approve", "approve", approve_col), ("Reject", "reject", reject_col),
        ):
            with column:
                if st.button(label, key=f"{verdict}_{request_id}_{role}", width="stretch"):
                    with st.spinner("Recording decision…"):
                        for event in submit(request_id, acting_as, role, verdict, comment):
                            render_event(event.model_dump(mode="json"))
                    if verdict == "reject":
                        st.warning("Request rejected.")
                    elif db.get_request(request_id)["status"] == "COMPLETED":
                        st.success("All approvals received. Execution completed.")