"""Load and render a read-only evidence record for one Approva request."""

import json

import streamlit as st

from approva import audit, db
from approva.engine.citations import validate_citations
from approva.schemas import Citation


def load_passport(request_id: str) -> dict | None:
    """Read one request and its persisted approvals, trace, tools, and artifacts."""
    request = db.get_request(request_id)
    if request is None:
        return None
    parsed = json.loads(request.get("parsed_json") or "{}")
    policy = json.loads(request.get("policy_json") or "{}")
    risk = json.loads(request.get("risk_json") or "{}")
    decision = json.loads(request.get("decision_json") or "{}")
    laya = json.loads(request.get("laya_json") or "{}")
    raw_citations = [Citation.model_validate(item) for item in policy.get("applicable_clauses", [])]
    citations, invalid = validate_citations(raw_citations)
    with db.connection() as conn:
        approvals = [dict(row) for row in conn.execute(
            "SELECT role,approver_id,verdict,ts,comment FROM approvals WHERE request_id=? ORDER BY id",
            (request_id,),
        )]
        trace = [json.loads(row["body_json"]) for row in conn.execute(
            "SELECT body_json FROM audit_events WHERE request_id=? ORDER BY seq", (request_id,),
        )]
        tool_calls = [dict(row) for row in conn.execute(
            "SELECT idem_key,tool,ok,ref_id,message,ts FROM tool_calls WHERE request_id=? ORDER BY ts",
            (request_id,),
        )]
        tickets = [dict(row) for row in conn.execute("SELECT id,queue,title,status FROM tickets WHERE request_id=?", (request_id,))]
        licenses = [dict(row) for row in conn.execute("SELECT id,vendor,item,seats,start_date FROM licenses WHERE request_id=?", (request_id,))]
        ledger = [dict(row) for row in conn.execute("SELECT id,kind,payee,amount_inr,category FROM ledger WHERE request_id=?", (request_id,))]
        outbox = [dict(row) for row in conn.execute("SELECT channel,recipient,subject,delivered FROM outbox WHERE request_id=?", (request_id,))]
    return {
        "request": request,
        "parsed": parsed,
        "policy": policy,
        "risk": risk,
        "decision": decision,
        "laya": laya,
        "citations": citations,
        "invalid_citations": len(invalid),
        "approvals": approvals,
        "trace": trace,
        "tool_calls": tool_calls,
        "tickets": tickets,
        "licenses": licenses,
        "ledger": ledger,
        "outbox": outbox,
    }


def render_passport(passport: dict) -> None:
    """Render the identity, evidence, authority, execution, and integrity record."""
    request = passport["request"]
    parsed = passport["parsed"]
    decision = passport["decision"]
    risk = passport["risk"]
    st.title("Decision Passport")
    st.caption("Evidence record · AI interpretation is advisory; policy and authorization controls determine what can happen.")

    st.subheader("Identity")
    st.json({
        "request_id": request["id"],
        "requester": request.get("requester_id"),
        "workflow": parsed.get("request_type"),
        "created_at": request.get("created_at"),
    })

    st.subheader("Decision")
    st.json({
        "final_decision": decision.get("type"),
        "request_status": request.get("status"),
        "risk_score": risk.get("score"),
        "risk_tier": risk.get("tier"),
        "required_roles": decision.get("required_roles", []),
    })

    st.subheader("Policy evidence")
    if passport["invalid_citations"]:
        st.warning(f"{passport['invalid_citations']} stored citation(s) failed revalidation and are hidden.")
    if passport["citations"]:
        for citation in passport["citations"]:
            st.markdown(f"> **{citation.clause_id}** — “{citation.quote}”")
    else:
        st.caption("No validated policy citations recorded.")

    st.subheader("Deterministic checks")
    checks = {
        "annualized_cost_inr": request.get("annual_cost"),
        "vendor_status": request.get("vendor_status"),
        "data_categories": parsed.get("data_categories"),
        "manipulation_signals": parsed.get("manipulation_signals"),
        "receipt_attached": parsed.get("receipt_attached"),
        "policy_violations": passport["policy"].get("violations"),
        "risk_factors": risk.get("factors"),
    }
    st.json({key: value for key, value in checks.items() if value is not None})

    st.subheader("AI interpretation")
    st.caption("Structured extraction and policy interpretation; not the final decision.")
    st.json({
        "parsed_request": parsed,
        "policy_reasoning": passport["policy"].get("reasoning"),
        "policy_roles_proposed": passport["policy"].get("required_roles"),
    })

    st.subheader("Laya second opinion")
    laya = passport["laya"]
    st.caption(f"Status: {laya.get('status', 'UNRECORDED')} · non-authoritative, tighten-only")
    if laya:
        st.json(laya)

    st.subheader("Human approval")
    if passport["approvals"]:
        st.dataframe(passport["approvals"], hide_index=True, width="stretch")
    else:
        st.caption("No human approval recorded.")

    st.subheader("Gateway and execution")
    gateway = [event for event in passport["trace"] if event.get("step") == "gateway.authorize"]
    if gateway:
        st.dataframe([
            {"result": event.get("detail", {}).get("result"), "tool": event.get("detail", {}).get("tool"),
             "reason": event.get("detail", {}).get("reason"), "idempotency_key": event.get("detail", {}).get("idempotency_key")}
            for event in gateway
        ], hide_index=True, width="stretch")
    else:
        st.caption("No Gateway action authorization recorded yet.")
    artifacts = {
        "mock_tickets": passport["tickets"],
        "mock_licenses": passport["licenses"],
        "mock_ledger": passport["ledger"],
        "notifications": passport["outbox"],
        "tool_calls": passport["tool_calls"],
    }
    st.json(artifacts)

    st.subheader("Audit integrity")
    if st.button("Verify audit chain", key=f"verify_passport_{request['id']}"):
        ok, broken_sequence = audit.verify_chain()
        st.session_state[f"passport_audit_{request['id']}"] = (ok, broken_sequence)
    verified = st.session_state.get(f"passport_audit_{request['id']}")
    if verified is None:
        ok, broken_sequence = audit.verify_chain()
    else:
        ok, broken_sequence = verified
    if ok:
        st.success("Audit chain: VERIFIED")
    else:
        st.error(f"Audit chain: BROKEN at sequence {broken_sequence}")