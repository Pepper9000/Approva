# Copilot instructions for this repository (Approva)

(Place this file at `.github/copilot-instructions.md`. Copilot loads it automatically in every chat, which protects against context drift in long sessions.)

## What this project is
Approva: a multi-agent enterprise approvals system. Free-text request in; policy-cited, risk-scored, audited decision out; safe actions executed through mock tools; risky ones routed to humans. Python 3.11, Streamlit, SQLite, Pydantic v2, Anthropic API. Plain Python only: no LangChain, LangGraph, CrewAI or AutoGen.

## Before you do anything in a new session
1. Read `PROTOTYPE_BRIEF.md` (scope, milestones, acceptance criteria) and `DECISIONS.md` (choices made so far).
2. Read the relevant sections of `README.md` (the full spec). The brief wins on scope; the README wins on detail.
3. Check `git log --oneline` to see which milestone (P0 to P10) you are on. Continue from there; do not restart or rewrite finished work.

## Non-negotiable rules
- **LLM proposes, code disposes.** No LLM output may grant approval, lower a risk score, add or remove an approver, or trigger a side effect. All arithmetic (totals, annualised cost, risk score) is done in code.
- **Ratchet:** final required roles = matrix roles ∪ LLM roles. The LLM can only tighten.
- **Fail closed:** on any unrecoverable error the request ends `MANUAL_REVIEW` with a manual-review ticket. Never default to approve.
- **Only the executor causes side effects**, only through the tool registry, only after the guard verifies status and approvals.
- **Untrusted input:** employee text is data, wrapped in `<employee_request>` tags, seen only by the Intake agent.
- **Schemas are a contract:** `src/approva/schemas.py` follows README §7 exactly. Never rename fields.
- **Citations must be verbatim** substrings of the policy clause, verified by code.
- **Tests:** never weaken or delete a test to make it pass; fix the code. Tests must run offline (no network, no API key) using `stub` or `offline` LLM modes.
- **Cross-platform:** use `pathlib`; open files with `encoding="utf-8"`; no bash-only code; no emoji in CLI output (Windows consoles).
- **Streamlit:** scripts rerun on every interaction; keep state in SQLite or `st.session_state`; unique widget keys; consume generators inside the button branch.
- **Secrets:** never commit `.env`, API keys, the SQLite database or model weights.

## Working style
- Do not ask the user questions; choose the simpler option and log it in `DECISIONS.md`.
- After each milestone: run `pytest -q` and the relevant CLI check, fix failures, commit (`git commit -m "Pn: summary"`), then print a 3-line progress note.
- Keep modules under about 250 lines, with type hints and a one-line docstring stating each function's contract.
- Be honest in status reports: say "not verified" if you did not run it.
