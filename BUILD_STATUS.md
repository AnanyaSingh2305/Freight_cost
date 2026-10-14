# Implementation status

The working project has been implemented phase by phase and exercised on the complete supplied dataset.

The interface has been refined with clearer system typography, a minimal sidebar, readable status labels, and explanatory baseline cards. Desktop and mobile layouts have been inspected in the live browser. See `results/ui_checks.json` for that UI verification record. A subsequent explanation update adds route-week metrics, threshold triggers and relevant evidence failures to the CSV reason field; all seven other columns are identical to the earlier downloaded export. See `results/explanation_checks.json`.

| Phase | Status | Evidence |
|---|---|---|
| A: validation and weekly metrics | Complete | Strict CSV checks; 728 weekly groups; independent weighted-rate, calendar-window, peer and no-look-ahead fixtures |
| B: anomaly policy and exact export | Complete | Configurable 15% default; three supplied example rows match costs, comparisons, flags and note IDs |
| C: semantic retrieval and grounded evidence | Complete | Pinned MiniLM model via FP32 ONNX CPU inference; exact source quotes; route/time/effect/coverage/magnitude guards |
| D: evaluation and reproducibility | Complete | 43 tests pass; 20 labeled evidence cases pass; three fresh-process CSV and full-audit hashes match |
| E: dashboard and constrained questions | Complete | AppTest passes nine checks, including explanation freshness; live browser confirms the review queue, route chart, N002 evidence and grounded March answer |
| Packaging and walkthrough | Complete | Exact CSV, audit, cost/evaluation reports, dependency pins, README, launcher and ten-minute walkthrough |

## Full-data result at the default threshold

- Shipments: **2,940**.
- Directed routes: **7**.
- Route-weeks: **728**.
- Unusual rising-cost candidates: **26**.
- Supported by applicable context: **3**.
- Unexplained and flagged for review: **23**.
- Normal rows: **702**.

The three context-supported candidates are Ahmedabad-Mumbai during the January 20, 2025 festival week and Chennai-Bangalore during the weeks of February 24 and March 3, 2025. The expired flood explanation is rejected for later March weeks.

Candidate-count sensitivity: 81 at 10%, 26 at 15%, and 19 at 20%. The threshold is an explicit policy choice, not a supplied company cutoff.

## Verification

- `results/evaluation.json`: all 43 automated tests pass and all 20 reviewed evidence-suitability cases pass. No unsupported justification was produced on this small development set. This is not a held-out anomaly accuracy claim.
- `results/reproducibility.json`: three independent processes generate identical CSV bytes and full audit reports. CSV SHA-256: `5490cf0e1abfed4e62263e1484ed6f58f7bb00040b3d6f9c13813065be021a2e`.
- `results/encoder_verification.json`: all ten ONNX note embeddings match independently generated Sentence Transformers reference vectors within `1e-5` tolerance. Maximum absolute difference is approximately `1.64e-7`.
- `results/dashboard_checks.json`: initial render, summary metrics, review queue, route selection, grounded question answer, real semantic inference, and threshold/lexical rerun pass with zero application exceptions.
- `results/explanation_checks.json`: the eight-column contract is preserved, all seven non-reason columns match the earlier export across 728 rows, and representative explanations are recorded. Reasons vary with measured facts; unknown causes remain unexplained.
- `results/live_browser_checks.json`: the running local dashboard was verified in the browser; `results/dashboard_preview.jpg` shows the live opening view.
- `results/token_cost_log.json`: actual local encoder tokens and inference batches are recorded separately from generative usage. Zero generative LLM calls and USD 0 API spend.

## Running it locally

The local dashboard is available at `http://127.0.0.1:8501/` while its server remains running. VS Code includes a **FreightTiger: live dashboard** F5 configuration and dashboard/test tasks. From this project directory, `./run_demo.ps1` also works in PowerShell and validates environment imports first. In a fresh copy, follow README to create `.venv` and install the pinned dependencies first.

The numerical CLI and lexical mode use Python's standard library. The dashboard uses pandas/Streamlit; semantic mode adds ONNX Runtime and Tokenizers. Model files download once from the pinned public repository and remain in `.cache`, outside the submission ZIP.

Validation commands:

```powershell
python -m unittest discover -s tests -v
python -m freight_assistant.evaluate --offline
python -m freight_assistant.reproduce --offline
python -m freight_assistant.verify_encoder
python scripts/check_dashboard.py
```

## Practical limits

Browser visual inspection now passes against the running local server. The review queue, route chart with original supporting evidence, and question answering have been exercised. VS Code run configurations and launcher syntax are validated; the existing live server was reused rather than starting a conflicting second copy on port 8501.

The supplied ten notes use reviewed source metadata. New or altered notes require review before they can justify costs. The interface supports route/month questions; it is not an unrestricted chatbot. Applicable context is a supported explanation, not proof of exact causality. These assumptions are described in README and the audit.

The dependency graph and pinned versions were checked with Python 3.12 and the project-local Python 3.14.3 environment. The latter passes dependency checks, all tests, semantic evaluation and three-run reproducibility. Its interpreter configuration has been aligned with its installed Python 3.14 packages. A separate clean-machine installation was not performed.
