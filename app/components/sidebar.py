"""Shared acting-as, mode, and demo reset controls."""

import streamlit as st

from approva import config, db


def _ensure_seeded() -> None:
    """Create the demo database and its reference data on first page load."""
    db.init_db()
    with db.connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
    if count == 0:
        db.seed_from_yaml()


def render_sidebar() -> str:
    """Render common controls and return the currently acting employee ID."""
    _ensure_seeded()
    with db.connection() as conn:
        people = conn.execute("SELECT id,name FROM employees ORDER BY id").fetchall()
    identifiers = [person["id"] for person in people]
    names = {person["id"]: person["name"] for person in people}
    if st.session_state.get("acting_as") not in identifiers:
        st.session_state["acting_as"] = "E001" if "E001" in identifiers else identifiers[0]
    st.sidebar.selectbox(
        "Acting as", identifiers, format_func=lambda employee_id: names[employee_id], key="acting_as",
    )
    mode = config.llm_mode()
    st.sidebar.caption(f"LLM mode: {mode.upper()}")
    if mode == "stub":
        st.sidebar.warning("STUB MODE: canned AI responses, not live")
    if st.sidebar.button("Reset demo data", key="reset_demo_data"):
        db.reset_demo()
        st.sidebar.success("Demo data reset.")
    return st.session_state["acting_as"]