# Approva Prototype Status

Updated: 2026-10-02. Milestones P0-P9 are implemented. P10 stretch work was not started.

## How to Run

From the repository root on Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install -e .
Copy-Item .env.example .env
$env:LLM_MODE = "stub"
python -m approva.cli reset
python -m approva.cli seed
python -m approva.cli run "Need Figma licenses for 5 designers, ~₹6,300/seat/month, starting Monday." --as E001
python -m streamlit run app/Home.py
python -m pytest -q
```

The prototype was verified with Python 3.14.2 in the workspace venv. Requirements installation, editable installation, and `import approva` passed there. A clean-clone setup with the exact venv-creation sequence was not run.

## Success Criteria

| Criterion | Result | Evidence |
|---|---|---|
| S1 | ⚠️ Partial | `pip install -r requirements.txt`, `pip install -e .`, and import path passed in the configured Python 3.14.2 venv; a clean-clone setup was not run. |
| S2 | ✅ Verified | `pytest -q`: 65 passed; tests use stub/offline paths and need no API key. |
| S3 | ✅ Verified | CLI Scenario A: risk 15 LOW, `REQUIRE_APPROVAL [manager]`, `AWAITING_APPROVAL`; E002 approval completed with `TKT-0001`, `LIC-0001` (5 seats), and two outbox messages. |
| S4 | ✅ Verified | AppTest submitted Scenario A and rendered trace, citations, risk score, and result; acting as E002 approved it and the page rendered Executor guard/provisioning events. |
| S5 | ✅ Verified | A `REQUIRE_APPROVAL [manager]`; B `AUTO_APPROVE`, risk 0 and completed; C `ESCALATE [manager, finance, legal, security]`, risk 90; D `ESCALATE [manager, finance, security]`, risk 60. |
| S6 | ✅ Verified | Executor tests reject `AWAITING_APPROVAL`, missing roles, any rejection, and a `REJECT` decision; repeated execution produces no duplicate artifacts. |
| S7 | ✅ Verified | Audit unit tests detect tampering at each chain position. CLI verified the chain, tampered seq 110, then reported `Audit chain broken at seq 110`. |
| S8 | ✅ Verified | Forced `ServiceUnavailable` ends `MANUAL_REVIEW`, creates a Manual Review ticket containing the original request, and never approves. |
| S9 | ✅ Verified | AppTest confirms every page shows the LLM mode caption and the exact visible stub-mode banner. |
| S10 | ✅ Verified | This status report records evidence and limitations. |

## Known Issues

- No live Anthropic call was made; no API key was used, and no live response cache was recorded. Live API compatibility remains unverified.
- S1 remains partial because a clean-clone setup was not exercised from scratch.
- The Audit page and other stretch items were not built; audit verification and tamper controls are available through the CLI.
- P10 was not started because S1 is not fully verified.

Implementation decisions and small specification choices are recorded in [DECISIONS.md](DECISIONS.md).

## Two-Minute Demo

1. Run `python -m streamlit run app/Home.py` and open Submit.
2. Leave Acting as set to Asha, click Scenario A, then Submit request. Show the SW-1.1/SW-1.2 quotes, risk 15 LOW, and manager approval result.
3. Open Approvals, switch Acting as to Rohan, and click Approve. Show the execution trace, ticket, five-seat license, and notifications.
4. Return to Submit, switch Acting as to Asha, click Scenario C, then Submit request. Show risk 90 HIGH, the four required roles, and the policy citations.
