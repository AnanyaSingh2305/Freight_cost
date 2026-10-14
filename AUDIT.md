# Project audit

Date: 15 October 2026. Scope: the local CLI and dashboard, input/configuration handling, numerical boundaries, saved analysis, semantic caches and the supplied-data regression results.

The original 43 tests passed before the audit. Additional checks reproduced failures outside that coverage. The six issue groups below have been fixed, with regression checks added. This is a functional and robustness audit; it is not a penetration test or a guarantee that every possible input is supported.

## Findings and fixes

| ID | Priority | Failure before the fix | Current behaviour |
| --- | --- | --- | --- |
| A01 | High | Saved results checked source code but not input hashes. Changing a shipment file could leave stale results displayed; the interactive cache could reuse the old analysis too. | Cache keys include code, all four data inputs and configuration. Saved input/source hashes must match. An existing session recomputes after an input change; a fresh session rejects stale saved results. |
| A02 | Medium | `100 × (2.3 / 2 − 1)` is slightly below 15 in binary floating point. An exact 15% rise could miss the inclusive threshold. | Detection, reason text and the nationwide/peer guard use a shared comparison with a `1e-9` percentage-point tolerance. A genuinely lower value such as 14.999999% still does not pass. |
| A03 | Medium | Unknown config keys raised `TypeError`; incomplete annotations or model manifests raised `KeyError`. Boolean numeric settings were accepted. The dashboard also used hardcoded evidence defaults instead of the settings in `config.json`. | Configuration and metadata structure/types are validated before use. Invalid files produce actionable validation errors. The dashboard uses the file's evidence defaults, with the selected threshold applied on top. |
| A04 | Medium | A malformed saved audit JSON crashed the dashboard before the user could run analysis. A malformed optional evaluation report could also crash rendering. | Invalid saved analysis produces a warning and leaves Run analysis available. Incomplete saved rows/evidence/cost data are rejected. Optional report parsing failures produce a warning without taking down the app. |
| A05 | Medium | Cached note vectors were loaded without checking their shape, numeric validity or normalization. Truncated arrays or the wrong document count could cause failures; invalid vectors could enter ranking. | Derived caches are checked for a floating array of shape `(number of notes, 384)`, finite values and unit-length vectors. Invalid derived caches are discarded and rebuilt from the verified model. Changed model artifacts still fail their integrity check. |
| A06 | Medium | Finite but extreme input values could produce an infinite percentage, or an intermediate sum could raise an unhandled overflow. | Unrepresentable percentages and weekly totals raise clear numeric-range errors. A representable historical/peer mean uses a scaled fallback if its intermediate sum overflows. Oversized configuration numbers are rejected. |

## How the failures were checked

- **Saved-data freshness:** in an isolated copy, change the shipment input while leaving the saved source hashes unchanged. Before the fix, the dashboard accepted the stale audit. After the fix, a fresh session refuses it and an active session recomputes using the new input hash.
- **Saved-file recovery:** replace the isolated audit with invalid JSON. Before the fix, Streamlit recorded an application exception. After the fix, it displays a warning and successfully runs the lexical analysis when requested.
- **Input errors:** use an unknown configuration field, incomplete annotation and incomplete model manifest. The previous code raised unhandled type/key errors; regression tests now require validation errors. The CLI test checks its nonzero exit and useful error text.
- **Numerical boundaries:** check the exact 15% decimal example, a slightly lower value, an unrepresentable percentage, an overflowing weekly total and a large but representable history mean.
- **Derived cache files:** test truncated data, the wrong shape/document count, zero vectors, NaN values and an unexpected archive format. Also check that valid normalized vectors are reusable.

The dashboard failure scenarios use temporary copies and real lexical recomputation. They do not modify the live shipment records or context notes. See [`scripts/audit_dashboard.py`](scripts/audit_dashboard.py) and [`tests/test_audit_regressions.py`](tests/test_audit_regressions.py).

## Verification after the fixes

| Check | Result | Evidence |
| --- | --- | --- |
| Automated tests | 63 pass in the tested environment | [`evaluation.json`](results/evaluation.json) |
| Reviewed evidence cases | 20 pass; no unsupported justification in this development set | [`evaluation.json`](results/evaluation.json) |
| Dashboard workflow | Nine checks pass | [`dashboard_checks.json`](results/dashboard_checks.json) |
| Dashboard failure recovery | Six checks pass with zero application exceptions | [`robustness_checks.json`](results/robustness_checks.json) |
| Semantic encoder | Matches the independent reference within the recorded tolerance | [`encoder_verification.json`](results/encoder_verification.json) |
| Independent reruns | Three processes produce identical CSV and full-audit hashes | [`reproducibility.json`](results/reproducibility.json) |
| Installed dependencies | `pip check` reports no broken requirements in the exercised environment | Command executed during audit |
| Supplied-data output | Byte-for-byte unchanged by these fixes | SHA-256 below |

The output still contains 728 route-weeks: 702 normal, three justified and 23 unexplained. Its SHA-256 remains:

```text
5490cf0e1abfed4e62263e1484ed6f58f7bb00040b3d6f9c13813065be021a2e
```

Run the standard checks in [README](README.md#validation-and-reproducibility), then run the added recovery checks:

```powershell
.\.venv\Scripts\python.exe scripts/audit_dashboard.py
```

## Remaining limits

The evidence annotations still require review for new notes. The labeled cases are a development set, not a held-out measure of production anomaly accuracy. The application remains local and file-based; multi-user load, authentication, production ingestion, package vulnerability scanning and deployment security were outside this audit. A clean-machine installation was not repeated. Cached results are an integrity/freshness mechanism, not a security boundary against someone who can rewrite the entire local project and its hashes.
