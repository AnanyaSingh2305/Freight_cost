# Design decisions

The central problem is deciding which cost increases deserve attention and which have a credible explanation. A convincing sentence is not enough: the explanation has to fit the route, the shipments and the dates.

This document explains the choices behind the implementation, including assumptions that go beyond the case-study brief. It describes the current code, rather than a proposed production system.

## 1. Keep the calculations and verdicts explicit

The numerical path uses ordinary Python rules for aggregation, baselines and anomaly detection. The same rules decide whether a note can justify a rise. Neural AI helps retrieve relevant context.

This makes a result easier to investigate. If a reviewer questions a flag, the audit shows the rate, both baselines, the threshold and every evidence check. There is no generated intermediate answer to reconstruct.

The tradeoff is flexibility. The pipeline cannot interpret arbitrary new business language on its own. That is a reasonable limit for this small, supplied dataset, but it needs to remain visible when describing the project as an AI application.

Implementation: [`pipeline.py`](freight_assistant/pipeline.py), [`detection.py`](freight_assistant/detection.py), [`evidence.py`](freight_assistant/evidence.py).

## 2. Weight shipment rates by the work performed

A small shipment should not have the same influence on a weekly rate as a much larger shipment. The weekly calculation therefore divides total freight cost by total tonnes multiplied by kilometres.

For example, shipments costing INR 100 for 10 tonne-km and INR 900 for 300 tonne-km have a combined rate of **INR 1,000 / 310 = INR 3.23 per tonne-km**. Averaging their individual rates would give INR 6.50 and describe the week's transport work poorly.

Routes remain directed: Ahmedabad–Mumbai and Mumbai–Ahmedabad are separate routes. Peer groups use the supplied route type, rather than an invented distance classification.

Implementation: [`metrics.py`](freight_assistant/metrics.py), [`validation.py`](freight_assistant/validation.py).

## 3. Give history and peers different jobs

History asks whether this route has become more expensive than it recently was. Peers ask whether it is expensive compared with other routes of the same type this week. Both comparisons help, but they answer different questions.

History uses the previous eight **calendar weeks**, excluding the current week. If a week is missing, the calculation uses the remaining observations in that window. It does not fill the gap with zero or reach farther back for an eighth observation. This avoids quietly changing the meaning of “recent history.”

Each peer route gets one vote in the same-week mean, and the current route is excluded. Weekly shipment rates are weighted by transport work; the mean across route-level rates is arithmetic. Those are separate aggregation choices.

A zero or missing baseline produces an undefined percentage, not a zero-percent change. A positive cost after a zero history baseline can still be a real rise and is handled explicitly.

Implementation: [`metrics.py`](freight_assistant/metrics.py), [`test_metrics.py`](tests/test_metrics.py).

## 4. Treat the 15% threshold as an assumption

The brief asks for unusual increases without prescribing a cutoff. The default is 15% above history **or** peers, together with a positive rise versus history **or** the previous observed week.

The rise condition matters. A route may consistently cost more than its peers because of characteristics missing from this dataset. A stable peer premium alone should not be described as a new increase. Conversely, a route can rise week over week and cross the peer threshold while staying below the history threshold.

The default is configurable, and the reports expose how sensitive the result is: 10%, 15% and 20% produce 81, 26 and 19 candidates respectively. These counts do not establish which threshold is best. Choosing one for operational use would require labeled examples and a view of the cost of missed issues versus unnecessary reviews.

The zero-baseline case is an explicit exception to percentage comparisons because dividing by zero cannot produce a meaningful percentage.

Implementation: [`config.json`](config.json), [`detection.py`](freight_assistant/detection.py), [`results/summary.json`](results/summary.json).

## 5. Use a local encoder and a small index

Semantic retrieval uses the pinned MiniLM sentence encoder through ONNX Runtime and Hugging Face Tokenizers. This provides meaning-based matching on the CPU without an inference API key or a service to deploy.

There are only ten notes. A local vector matrix and cosine similarity are enough for that corpus. A vector database would add installation and operational work without solving a present scale problem. If the note collection grew substantially, indexing and retrieval performance would need to be revisited.

Direct ONNX inference keeps the runtime separate from model-training dependencies. It also creates responsibility for tokenization, pooling and normalization, so the repository includes an independent Sentence Transformers embedding reference and a parity check. Model revision and artifact hashes are pinned; note-vector caches depend on the source text and model/backend identity.

The lexical baseline is available when a model download is impractical. It is a visible choice, and semantic failures remain visible rather than silently changing the retrieval method.

Implementation: [`retrieval.py`](freight_assistant/retrieval.py), [`download_model.py`](freight_assistant/download_model.py), [`verify_encoder.py`](freight_assistant/verify_encoder.py).

## 6. Separate finding a note from accepting it

A note can sound relevant and still be unsuitable evidence. A flood note for the right route may refer to the wrong week. A nationwide fuel increase may affect everyone without explaining one route's premium over peers.

Retrieval orders the notes, but eligibility comes from explicit checks. All ten notes are considered after ranking, so a top-k cutoff cannot hide valid evidence in this small corpus. When multiple notes qualify, route-specific evidence takes precedence, followed by retrieval score and note ID for deterministic ordering.

That means retrieval rank alone does not determine recall in this version. The evidence rules do much of the work, and the documentation should say so. A larger corpus would need a genuine candidate-retrieval stage and separate evaluation of missed evidence.

Implementation: [`evidence.py`](freight_assistant/evidence.py), [`evaluate.py`](freight_assistant/evaluate.py).

## 7. Make note interpretation reviewable

The supplied notes are short enough to review individually. Their event dates, cost effect, exact supporting quote and interpretation are recorded in `note_annotations.json`, together with a source hash. These are descriptions of the notes, not preassigned route-week verdicts.

This choice makes ambiguous interpretations inspectable. The festival note is interpreted as its Monday–Sunday week. The flood note covers 24 February through 8 March 2025; shipments after that window cannot inherit the explanation. The fuel note starts on 5 May 2025 and has no stated end.

If a note's source text changes, its annotation must be reviewed. An unreviewed note can be retrieved but cannot justify a rise. The tradeoff is manual review: this implementation does not claim automatic understanding of arbitrary new notes. A future extraction model would need validation and a review path before its output could authorize verdicts.

Implementation: [`note_annotations.json`](data/note_annotations.json), [`evidence.py`](freight_assistant/evidence.py).

## 8. Check how much of the week an event actually covers

An event lasting one day should not automatically explain an entire weekly result. Coverage is measured using shipment tonne-km inside the event window and on or after the note's publication date. The default acceptance level is 75%.

This is a conservative implementation assumption, not a company-supplied rule or a confidence probability. It can leave a real but short disruption unexplained. The benefit is that a small overlap cannot excuse the whole week's increase. Accepted explanations show their actual coverage.

Quantified notes also face a magnitude check with a two-percentage-point tolerance. The roughly 5–7% fuel increase cannot justify an arbitrarily large history-relative jump. It cannot explain a peer premium, and an old persistent event cannot establish a new rise once it is already present in every history week. Unquantified flood or festival context supports an explanation without proving the exact amount caused.

Implementation: [`evidence.py`](freight_assistant/evidence.py), [`config.json`](config.json), [`test_evidence.py`](tests/test_evidence.py).

## 9. Keep unknown causes unknown

An unexplained rise is still useful: it tells a reviewer where to investigate. The app should not fill an evidence gap with a plausible story about demand, fuel or transporter behaviour.

The original reasons repeated generic status sentences. The explanation update now includes the route-week's cost, history and peer baselines, threshold trigger and relevant rejected context. A March Chennai–Bangalore row can explain that the flood window has expired; a Mumbai–Pune peer premium can explain why nationwide fuel context is insufficient.

Some rows can legitimately share a verdict or a cause. Different wording is not the goal. The goal is to show the facts that distinguish the rows while leaving unsupported causes unresolved. `matched_note_id` stays blank for unexplained rows even if the reason mentions a rejected note.

Implementation: [`explanations.py`](freight_assistant/explanations.py), [`results/explanation_checks.json`](results/explanation_checks.json).

## 10. Keep one pipeline behind the UI and CLI

Streamlit suits a local demonstration with filters, charts, evidence inspection and CSV downloads. Both the dashboard and CLI call the same analysis function, which prevents two versions of the business rules from drifting apart.

The settings form requires **Run analysis** to apply changes. Results retain their active configuration, and source changes invalidate cached analyses while preserving the chosen threshold and retrieval mode. Dashboard downloads reflect the session; the CLI writes the saved submission artifacts.

The question interface filters existing results by a named route and an optional month/year. It does not generate an unrestricted answer or execute arbitrary queries. This keeps answers traceable, at the cost of a narrower question format.

Implementation: [`app.py`](app.py), [`pipeline.py`](freight_assistant/pipeline.py), [`questions.py`](freight_assistant/questions.py).

## 11. Preserve the submission format and keep detail in the audit

The CSV keeps the sample's exact eight-column order. Every observed route-week is exported, including normal rows. The three states are `No`, `Yes` and `No (justified)` so a reviewer can distinguish an ordinary week from an unusual but context-supported week.

Full-precision values, candidate flags, evidence rejections, source hashes and environment details belong in the JSON audit. This keeps the submission compatible with the sample while leaving enough detail to investigate a result. Rounding is reserved for presentation and export.

Git attributes preserve file bytes because the recorded source/input hashes and CSV reproducibility checks would otherwise be affected by automatic line-ending conversion.

Implementation: [`reporting.py`](freight_assistant/reporting.py), [`validation.py`](freight_assistant/validation.py), [`.gitattributes`](.gitattributes).

## 12. Report what the checks establish

The validation combines hand-calculated numerical fixtures, integration checks, the three supplied sample rows, 20 reviewed evidence cases and dashboard interactions. Three fresh processes check reproducibility. An independent reference checks the local encoder implementation.

These checks cover important failure modes, but they do not establish production anomaly accuracy. The evidence cases were used during development, and the company data does not include a complete set of anomaly labels. Even a perfect score on these cases should not be described as proof that every real-world explanation will be correct.

Usage reporting follows the same principle. There are no generative calls or billed API inference, but the local encoder still processes tokens and uses compute. Its actual input tokens, cache status and runtime are recorded separately. Zero API spend does not mean zero resource use.

Evidence: [`evaluation.json`](results/evaluation.json), [`reproducibility.json`](results/reproducibility.json), [`dashboard_checks.json`](results/dashboard_checks.json), [`token_cost_log.json`](results/token_cost_log.json).

## What would change beyond the case study

The [functional audit](AUDIT.md) exposed an additional requirement: a saved result is useful only if its inputs are still current. Dashboard cache keys now include source files, the data inputs and configuration. Saved analysis must also pass input/source hash checks and basic result integrity checks. Corrupt saved files can be regenerated from the UI; corrupt derived vector caches can be rebuilt from the verified model. These checks add some file hashing on each dashboard rerun, which is acceptable for this small local dataset.

The UI also reads the evidence defaults from `config.json`, keeping its settings consistent with the CLI. Threshold comparisons use a small floating-point tolerance so a mathematically exact 15% rise is not lost to binary rounding. This does not round genuinely lower increases up to the threshold.

A source update also needs the running server to use the new functions. The dashboard refreshes already imported analysis modules in dependency order when their source fingerprint changes. This addresses a stale-import failure found in the live server that a fresh-process test could not expose.

The next steps depend on real operational needs: collect labeled review outcomes to calibrate thresholds, evaluate unseen events, add a reviewed workflow for new notes, and introduce persistent ingestion and monitoring as volume grows. Authentication and access controls would be needed before sharing shipment data across users. Those are future extensions; the current deliverable remains a local, file-based application.
