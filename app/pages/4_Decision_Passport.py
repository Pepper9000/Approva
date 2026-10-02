import streamlit as st

from app.components.decision_passport import load_passport, render_passport
from app.components.sidebar import render_sidebar
from approva import db

st.set_page_config(page_title="Decision Passport · Approva", layout="wide")
render_sidebar()
with db.connection() as conn:
    request_ids = [row[0] for row in conn.execute("SELECT id FROM requests ORDER BY created_at DESC")]

if not request_ids:
    st.title("Decision Passport")
    st.info("Submit or run a request before opening its Passport.")
else:
    requested = st.query_params.get("request")
    default = request_ids.index(requested) if requested in request_ids else 0
    request_id = st.selectbox("Request", request_ids, index=default, key="passport_request")
    passport = load_passport(request_id)
    if passport:
        render_passport(passport)