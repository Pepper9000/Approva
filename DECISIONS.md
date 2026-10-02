# Decisions

- P0: Use the specified `src/approva` package layout and setuptools editable install so CLI, tests, and Streamlit share one import path.
- P0: Keep the documented default `LLM_MODE=live`; offline tests and demos will explicitly select `stub` or `offline`.
