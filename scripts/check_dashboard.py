"""Exercise the actual Streamlit script using its supported testing API."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from streamlit.testing.v1 import AppTest


def no_exceptions(app):
    errors = [str(error.value) for error in app.exception]
    if errors:
        raise AssertionError(errors)


app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120).run()
no_exceptions(app)
assert len(app.metric) >= 4
assert len(app.dataframe) >= 1
checks = ["initial render", "summary metrics", "review queue"]
saved_rows = app.session_state["analysis"]["rows"]
assert all(f"week of {row['week_of']}" in row["reason"] for row in saved_rows)
assert all("/tonne-km" in row["reason"] for row in saved_rows)
checks.append("row-specific explanations in saved results")
app.selectbox(key="explorer_route").select("Chennai-Bangalore").run()
no_exceptions(app)
checks.append("route explorer selection")
question_button = next(button for button in app.button if button.label == "Show findings")
question_button.click().run()
no_exceptions(app)
assert any("N001" in str(element.value) for element in app.markdown)
checks.append("grounded route/month answer")
# Run the actual neural backend through the same form used in the demo.
run_button = next(button for button in app.button if button.label == "Run analysis")
run_button.click().run()
no_exceptions(app)
assert app.session_state["analysis"]["audit"]["retriever"]["mode"] == "semantic"
assert app.session_state["analysis"]["audit"]["summary"]["verdict_counts"]["justified"] == 3
checks.append("semantic inference rerun")
# Exercise a real computation rather than only rendering saved data.
evidence_select = next(widget for widget in app.selectbox if widget.label == "Evidence search")
evidence_select.select("Lexical · offline baseline")
app.slider[0].set_value(20)
run_button = next(button for button in app.button if button.label == "Run analysis")
run_button.click().run()
no_exceptions(app)
assert app.session_state["analysis"]["audit"]["configuration"]["anomaly_threshold_pct"] == 20
checks.append("interactive threshold and actual rerun")
app.session_state["analysis"]["revision"] = "previous source version"
app.run()
no_exceptions(app)
assert app.session_state["analysis"]["audit"]["configuration"]["anomaly_threshold_pct"] == 20
assert app.session_state["analysis"]["audit"]["retriever"]["mode"] == "lexical"
assert app.session_state["analysis"]["revision"] != "previous source version"
checks.append("source update refreshes cached explanations and preserves active settings")
report = {"passed": True, "checks": checks, "exceptions": 0,
          "visual_verification": "Separate live-browser evidence is recorded in results/live_browser_checks.json when available.",
          "method": "Streamlit AppTest executes app.py and its widget interactions; not a browser screenshot test."}
(ROOT / "results/dashboard_checks.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, indent=2))
