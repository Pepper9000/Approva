import streamlit as st

from app.components.sidebar import render_sidebar

st.set_page_config(page_title="Approva", page_icon="A", layout="wide")
render_sidebar()

st.title("Approva")
st.subheader("One sentence in. A cited, risk-scored decision out.")
st.write("Approva turns internal requests into policy-grounded decisions, with safe actions executed and higher-risk requests routed to the right people.")

left, right = st.columns(2)
with left:
    st.page_link("pages/1_Submit.py", label="Submit a request", icon=":material/edit_note:")
with right:
    st.page_link("pages/2_Approvals.py", label="Open approvals", icon=":material/task_alt:")

st.divider()
st.caption("Start with the Figma license request to see citations, risk factors, and the approval hand-off.")