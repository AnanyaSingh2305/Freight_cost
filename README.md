# Freight cost assistant

A local application that tracks weekly shipping costs, detects unusual increases, and checks whether the supplied context notes support an explanation. The numerical calculations, flags and note IDs are deterministic. AI is used for semantic evidence retrieval; explanations quote validated source text.

## Quick start

Use Python 3.12 or 3.14. Both local environments have been exercised. From this directory:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m freight_assistant
python -m streamlit run app.py
```

For this prepared local project, open the folder in VS Code and select **Run and Debug → FreightTiger: live dashboard**, then press **F5**. VS Code's Python Debugger extension is required for F5; **Terminal → Run Task → FreightTiger: run dashboard** also starts it without debugging. The project settings select `.venv/Scripts/python.exe`, so package installation and execution use the same interpreter. Open `http://127.0.0.1:8501/` once the terminal reports the server has started.

The PowerShell shortcut is `./run_demo.ps1`. It checks the chosen environment's imports before starting the server. If another copy is already running on port 8501, use that dashboard or stop its terminal with Ctrl+C before starting a second copy.

The first semantic run downloads the pinned `sentence-transformers/all-MiniLM-L6-v2` model. It runs on the CPU without an API key. Subsequent runs can operate offline:

```powershell
python -m freight_assistant --offline
```

You can download the model separately with `python -m freight_assistant.download_model`. All six inference artifacts are fetched from the exact pinned revision and recorded in a SHA-256 manifest. `requirements-lock.txt` pins the full tested dependency set; use it instead of `requirements.txt` when reproducing the tested environment.

For an immediate offline baseline, the analytical CLI and all numerical/evidence unit tests use only Python's standard library:

```powershell
python -m freight_assistant --retriever lexical --output-dir results/lexical
python -m unittest discover -s tests -v
```

Lexical mode uses TF-IDF/cosine ranking. It is an explicitly labeled baseline, not neural AI. There is no silent fallback from semantic to lexical retrieval.

## Case-study requirements and implementation

The dashboard uses an offline system-font stack, restrained orange accents and responsive summary cards. Review rows use plain-language statuses and are ordered by the largest history-relative increase. **Checks & cost** explains the weekly rate, historical baseline and peer baseline in readable cards; configuration details remain expandable. The exported submission CSV retains the case study's original schema and ordering. Styles are maintained in `assets/dashboard.css`.

| Requirement | Implementation |
|---|---|
| Route and supplied route type | Directed origin/destination; no inferred distance buckets |
| Monday-Sunday weeks | `week_of` is the Monday containing `shipment_date` |
| Weekly cost per tonne-km | Sum of freight costs divided by sum of shipment quantity × distance |
| Own history | Arithmetic mean of weekly rates in the prior eight calendar weeks; current week excluded |
| Similar routes | Same-week arithmetic mean of all other routes in the same route type |
| Unusual rising cost | Configurable threshold over either baseline, with a positive rise versus history or the previous observed week |
| Relevant context | Dense semantic ranking followed by route, time, cost-impact, coverage and magnitude checks |
| Grounded justification | Exact note quote, ID and event dates in reason; ID also in `matched_note_id` |
| No evidence | `Yes`, unexplained, and blank `matched_note_id` |
| Reproducibility | Three fresh-process runs compare full CSV and audit hashes |
| Evaluation | Independent numerical fixtures and 20 labeled evidence-suitability cases |
| Cost | Actual encoder input tokens and inference batches; separately zero generative LLM calls/output and zero API spend |

## Calculation choices

The weekly rate is:

```text
sum(freight_cost_inr) / sum(quantity_tonnes * distance_km)
```

This is a tonne-km-weighted shipment rate. It avoids averaging a tiny shipment equally with a large one. The supplied three example rows' rounded costs, percentage comparisons, flags and note IDs are checked against the output. These example checks supplement independently hand-calculated tests; the sample is not a complete labeled anomaly dataset.

History includes only observations within `[current Monday - 8 weeks, current Monday)`. When fewer than eight prior observations are available, use all available observations in that window. Do not pad, extrapolate, insert zero-cost weeks, or pull older observations outside the calendar window. The supplied dataset has no missing route-weeks, so an eight-observation and eight-calendar-week window coincide here.

Peer means give each other route one vote regardless of its shipment volume. Internal calculations retain floating-point precision using stable summation. CSV cost is rounded to two decimals and comparisons to one decimal with a signed percentage and the sample's suffix.

Missing or zero baselines produce `N/A (...)` comparison text, not fabricated zero changes. The audit retains null numerical differences and counts of available history/peers. No ratio can be computed against a zero baseline.

A positive rate after a zero historical rate is still an unusual rise and is flagged, while its undefined percentage remains `N/A`.

## Anomaly and export policy

The brief does not prescribe a threshold. The default `config.json` uses 15% over own history **or** peers, together with a positive increase over history **or** the previous observed week. A stable route that is structurally expensive versus peers does not pass the rise condition. Candidate-count sensitivity at 10%, 15% and 20% is saved in `summary.json`; the default was not optimized to reproduce sample labels.

Every observed route-week is exported. These choices are documented because the sample only illustrates unexplained and justified candidates:

- `No`: no unusual rising cost under the configured policy.
- `Yes`: unusual candidate with insufficient contextual evidence; human review required.
- `No (justified)`: unusual candidate with applicable supporting evidence.

The eight columns exactly match `sample_output_format_v2.csv`, in its original order. Detailed diagnostics stay in `audit.json`; they do not add CSV columns.

Each `reason` states the route/week, actual rate, historical and peer baselines, percentage differences and applicable threshold. Normal rows distinguish below-threshold costs from elevated costs without a qualifying rise. Flagged rows describe relevant evidence failures in plain language, such as an expired flood window or a nationwide event that cannot explain a peer premium. Justified rows retain the original note quote, event dates and shipment coverage. Shared verdicts or causes may legitimately recur; wording is never randomized and unsupported causes are never invented. Refreshing analysis after a source update preserves the active threshold and retrieval mode while invalidating stale explanations.

## Evidence and AI design

`retrieval.py` embeds the original notes and each anomaly question using an open-source sentence encoder pinned to commit `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`. With ten notes, a NumPy vector matrix and cosine similarity are sufficient; a separate vector-database service would add setup without improving this corpus. The small index is persisted using a hash of source text, backend and model revision. Unquantized ONNX CPU inference uses sequential execution and one thread. Tokenization, masked mean pooling and L2 normalization follow the model's configuration and model card. Ranked ties use note ID.

The implementation uses ONNX Runtime and Hugging Face Tokenizers directly to avoid importing training dependencies at startup. A first successful Sentence Transformers run supplied an independent embedding reference for checking the ONNX implementation. No fine-tuning is required for this small retrieval task.

All ten notes are considered after ranking, so a top-k cutoff cannot hide valid evidence. Route-specific eligible evidence takes precedence over nationwide evidence. No similarity score alone authorizes a justification.

`data/note_annotations.json` contains transparent, source-reviewed event metadata. These are not route-week anomaly labels. Each annotation carries the source hash, exact quote, dates, cost effect and an interpretation note. This intentionally makes the small supplied corpus auditable instead of asking a generative model to invent dates. Changed source text requires review; new unreviewed notes can be retrieved but cannot justify a verdict. Extending to arbitrary new notes would require a reviewed extraction workflow.

Specific interpretations and safeguards:

- Flood N001: February 24 through March 8, 2025. March 9 onward is outside the disruption window.
- Festival N002: the Monday-Sunday week containing January 20, 2025. This interpretation is explicit in the annotation.
- Fuel N003: persistent price level from May 5, 2025, with no stated end. It supports only a roughly 5-7% rise, with a configurable two-percentage-point tolerance. It cannot explain a route-specific peer premium or a new rise after the event is already reflected in all historical baseline weeks.
- Irrelevant tolls, no-cost-impact maintenance, normal conditions, recovery notices and absorbed compliance costs never support an increased-cost verdict.
- At least 75% of the week's shipment tonne-km must fall in the event window and occur on/after the note publication date. This conservative coverage threshold is a documented implementation assumption. A partial week explanation states its actual coverage.
- Unquantified disruption notes support a contextual explanation, not proof of the precise causal amount. This limitation is stated in every justified reason.

There is no generative LLM in the submitted pipeline. This avoids invented explanations, paid API dependencies and stochastic verdicts while retaining neural semantic retrieval. The optional question box supports a named route, an optional month and year, and returns computed findings with evidence. It is deliberately a constrained query interface, not an unrestricted chatbot.

## Validate and reproduce

```powershell
python -m unittest discover -s tests -v
python -m freight_assistant.evaluate --offline
python -m freight_assistant.reproduce --offline
python -m freight_assistant.verify_encoder
python scripts/check_dashboard.py
```

The evidence evaluation has 20 reviewed cases including wrong routes, dates before/after events, unaffected costs, recovery notes, insufficient magnitude, partial-week coverage and nationwide-vs-peer confusion. One positive case asks whether a 6% fuel rise has supporting context; it evaluates evidence suitability, not whether the default 15% detector would flag that row.

Results are development-time checks, not an independent held-out estimate of anomaly accuracy. We do not claim precision/recall for all anomalies because the company did not provide ground-truth anomaly labels.

Three CLI subprocesses recompute the full pipeline from unchanged inputs. Model weights and note vectors may be cached; route metrics, query embeddings, flags, evidence checks and output are recomputed. Full CSV and audit hashes are compared. Runtime and cache-use logs vary and are excluded from deterministic hash comparisons.

## Outputs

- `results/analysis_output.csv`: submission CSV.
- `results/audit.json`: full-precision metrics, raw candidates, note checks, annotations, input hashes and environment.
- `results/summary.json`: dataset counts and threshold sensitivity.
- `results/evaluation.json`: labeled cases and unit-test results.
- `results/reproducibility.json`: three independent runs and hashes.
- `results/token_cost_log.json`: actual encoder tokens, runtime, model revision, generative usage and API cost.
- `results/dashboard_checks.json`: dashboard test results when generated.
- `results/encoder_verification.json`: parity check against the initial Sentence Transformers reference embeddings.
- `results/live_browser_checks.json` and `results/dashboard_preview.jpg`: verification and preview of the locally running dashboard.
- `WALKTHROUGH.md`: ten-minute demo sequence.

For a full run, total model input tokens include actual local encoder tokens. There are zero generated text tokens and zero generative LLM calls. Model weights are local, so no published per-token API tariff applies and API spend is USD 0. Local CPU, memory, electricity and initial downloads still use resources. Download/setup work is excluded from per-run inference logs; cold vs warm note-vector cache status is recorded.

## Source layout

```text
freight_assistant/
  validation.py    strict ingestion and CSV contract
  metrics.py       weekly rates and both baselines
  detection.py     configurable anomaly policy
  retrieval.py     dense and lexical evidence ranking
  evidence.py      applicability and verdict checks
  reporting.py     exact CSV and audit serialization
  explanations.py measured comparisons and relevant evidence rejection messages
  pipeline.py      shared analysis path
  evaluate.py     reviewed evidence eval + unit tests
  reproduce.py    fresh-process repeat check
  questions.py    grounded route/month queries
app.py            Streamlit dashboard
tests/            independent fixtures and integration checks
data/             original CSVs and reviewed annotations
```

Technical references: [Sentence Transformers](https://www.sbert.net/examples/sentence_transformer/applications/semantic-search/README.html), [ONNX Runtime](https://onnxruntime.ai/docs/api/python/api_summary.html), [Streamlit charts](https://docs.streamlit.io/develop/api-reference/charts/st.line_chart), [pinned model](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/tree/1110a243fdf4706b3f48f1d95db1a4f5529b4d41).
