import streamlit as st

from app.components.sidebar import render_sidebar

st.set_page_config(page_title="Approva", page_icon="A", layout="wide")
render_sidebar()

st.title("Approva")
st.subheader("The approval and authorization firewall between requests and enterprise actions.")
st.write("AI interprets the request; deterministic policy, risk, human authority, and the Decision Gateway determine what can happen.")

left, middle, right, passport = st.columns(4)
with left:
    st.page_link("pages/1_Submit.py", label="Submit a request", icon=":material/edit_note:")
with middle:
    st.page_link("pages/2_Approvals.py", label="Open approvals", icon=":material/task_alt:")
with right:
    st.page_link("pages/3_Attack_Lab.py", label="Approval Attack Lab", icon=":material/security:")
with passport:
    st.page_link("pages/4_Decision_Passport.py", label="Decision Passport", icon=":material/fact_check:")

st.divider()
st.caption("AI proposes · Policy constrains · Humans authorize · Gateway executes · Audit proves")