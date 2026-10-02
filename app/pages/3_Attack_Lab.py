import streamlit as st

from app.components.sidebar import render_sidebar
from approva.attack_lab import attack_metrics, run_attack_suite

st.set_page_config(page_title="Attack Lab · Approva", layout="wide")
acting_as = render_sidebar()
st.title("Approval Attack Lab")
st.caption("Adversarial requests run through the same intake, policy, risk, decision, audit, and Gateway-backed execution pipeline.")
st.warning("The lab records only outcomes from this run. A nonzero unsafe-auto-approval count is a control failure.")

if st.button("Run eight adversarial tests", type="primary", key="run_attack_suite"):
    with st.spinner("Running requests through Approva…"):
        results = run_attack_suite(acting_as)
    st.session_state["attack_lab_results"] = results

results = st.session_state.get("attack_lab_results", [])
if results:
    metrics = attack_metrics(results)
    columns = st.columns(6)
    for column, (label, value) in zip(columns, metrics.items()):
        column.metric(label.replace("_", " ").title(), value)
    if metrics["unsafe_auto_approvals"]:
        st.error("Unsafe auto-approval detected. Treat this as a real authorization defect.")
    for item in results:
        with st.container(border=True):
            st.subheader(item["name"])
            st.caption(f"Request {item['request_id']} · {item['status']} · action {item['outcome']}")
            st.markdown(f"**Decision**  \n{item['decision']} · roles: {', '.join(item['required_roles']) or 'none'}")
            parsed = item["parsed"]
            signals = parsed.get("manipulation_signals", [])
            data = parsed.get("data_categories", [])
            st.markdown("**Detected signals**  \n" + (", ".join(signals) if signals else "None reported"))
            if data:
                st.markdown("**Data categories**  \n" + ", ".join(data))
            risk = item["risk"]
            if risk:
                st.progress(min(max(risk.get("score", 0), 0), 100), text=f"{risk.get('tier')} risk · {risk.get('score')}/100")
            st.caption(f"Side-effect tool calls: {item['tool_count']}")
            with st.expander("Structured result"):
                st.json({"parsed": parsed, "risk": risk, "decision": item["decision"], "roles": item["required_roles"]})
else:
    st.info("No Attack Lab run is stored in this session yet.")