"""Run with: python -m streamlit run app.py"""

from dataclasses import asdict
import hashlib
import importlib
import json
from pathlib import Path
import sys

import pandas as pd
import streamlit as st

import freight_assistant


def refresh_analysis_modules():
    """Refresh imported business rules when a running server sees changed source."""
    package_path = Path(freight_assistant.__file__).parent
    revision = tuple((path.name, hashlib.sha256(path.read_bytes()).hexdigest())
                     for path in sorted(package_path.glob("*.py")))
    if getattr(freight_assistant, "_dashboard_source_revision", None) == revision:
        return
    pipeline = sys.modules.get("freight_assistant.pipeline")
    workspace_root = getattr(pipeline, "ROOT", None)
    # Dependencies precede consumers so their imported function references refresh.
    for name in ("validation", "detection", "metrics", "download_model", "retrieval",
                 "explanations", "evidence", "reporting", "questions", "pipeline", "dashboard_state"):
        module = sys.modules.get(f"freight_assistant.{name}")
        if module is not None:
            importlib.reload(module)
    if workspace_root is not None:
        # Preserve an explicitly overridden root used for isolated app instances.
        sys.modules["freight_assistant.pipeline"].ROOT = workspace_root
    freight_assistant._dashboard_source_revision = revision


refresh_analysis_modules()

from freight_assistant.detection import Config, load_config
from freight_assistant.dashboard_state import analysis_revision, load_saved
from freight_assistant.pipeline import ROOT, analyze
from freight_assistant.questions import answer_question
from freight_assistant.reporting import csv_text

st.set_page_config(page_title="Freight cost monitor", page_icon="🚚", layout="wide")
try:
    defaults = load_config(ROOT / "config.json")
    ANALYSIS_REVISION = analysis_revision(ROOT)
except (OSError, ValueError) as exc:
    st.error(f"Project inputs or configuration could not load: {exc}")
    st.stop()
stylesheet = (ROOT / "assets/dashboard.css").read_text(encoding="utf-8")
st.markdown(f"<style>{stylesheet}</style>", unsafe_allow_html=True)


@st.cache_data(show_spinner=False)
def run_analysis(settings, mode, revision):
    rows, audit, cost = analyze(config=Config(**settings), mode=mode)
    return {"rows": rows, "audit": audit, "cost": cost, "revision": revision}


def comparison_basis(key):
    items = [
        ("01", "Weekly shipping cost", "Total freight cost divided by the transport work for a route that week.",
         "Transport work = tonnes × kilometres"),
        ("02", "The route's own history", "Compared with its average weekly rate over the previous eight calendar weeks.",
         "The current week is excluded"),
        ("03", "Other similar routes", "Compared with other routes of the same route type, during the same week.",
         "The selected route is excluded"),
    ]
    with st.container(border=True, key=key):
        for column, (number, title, description, formula) in zip(st.columns(3), items):
            with column:
                st.markdown(
                    f'<div class="basis-item"><div class="basis-number">{number}</div>'
                    f'<h4>{title}</h4><p>{description}</p>'
                    f'<span class="basis-formula">{formula}</span></div>', unsafe_allow_html=True)


def status_tone(value):
    return {
        "Needs review": "color: #a24f25; background-color: #fff6ee; font-weight: 600",
        "Explained": "color: #386956; background-color: #eef6f1; font-weight: 600",
        "Within range": "color: #66768a",
    }.get(value, "")


with st.sidebar:
    st.markdown(
        '<div class="brand"><div class="brand-mark">FT</div><div>'
        '<div class="brand-name">FreightTiger</div>'
        '<div class="brand-description">Shipping cost monitor</div></div></div>', unsafe_allow_html=True)
    st.markdown('<div class="sidebar-label">YOUR WORKSPACE</div>', unsafe_allow_html=True)
    st.caption("Understand the cost of every route.")
    with st.form("analysis_settings"):
        st.markdown("**Analysis settings**")
        threshold = st.slider("Unusual increase threshold (%)", 5, 50, min(50, max(5, round(defaults.anomaly_threshold_pct))), 1,
                              help="A lower threshold catches more increases. A route must also show a rise versus its past.")
        retrieval_label = st.selectbox("Evidence search", ["Semantic · local AI", "Lexical · offline baseline"],
                                      help="Semantic searches by meaning. Lexical uses matching words. Both apply the same evidence checks.")
        execute = st.form_submit_button("Run analysis", type="primary", width="stretch")
        st.caption("Apply your settings to update all results.")
    st.markdown(
        '<div class="sidebar-guide"><strong>A flag is a starting point.</strong>'
        '<p>We compare each route with its history and peers, then check the notes for a valid explanation.</p></div>',
        unsafe_allow_html=True)
    with st.expander("How to use this workspace"):
        st.write("1. Choose your threshold and evidence search.\n\n"
                 "2. Click Run analysis to apply your settings.\n\n"
                 "3. Review flagged weeks, inspect a route, or ask about the findings.")

st.markdown('<div class="eyebrow">SHIPPING INTELLIGENCE</div>', unsafe_allow_html=True)
st.title("Shipping costs, explained.")
st.markdown('<p class="hero-description">Spot unusual increases. Understand the context. Know what needs a closer look.</p>',
            unsafe_allow_html=True)

if "analysis" not in st.session_state:
    try:
        st.session_state.analysis = load_saved(ROOT, ANALYSIS_REVISION)
    except (OSError, ValueError) as exc:
        st.warning(f"Saved results could not load: {exc}. Click Run analysis to regenerate them.")
        st.session_state.analysis = None
elif (st.session_state.analysis is not None
      and st.session_state.analysis.get("revision") != ANALYSIS_REVISION):
    active = st.session_state.analysis["audit"]
    try:
        st.session_state.analysis = run_analysis(active["configuration"], active["retriever"]["mode"],
                                                 ANALYSIS_REVISION)
    except (OSError, ValueError, ImportError, RuntimeError) as exc:
        st.error(f"Updated analysis could not run: {exc}")
        st.stop()
if execute:
    settings = {**asdict(defaults), "anomaly_threshold_pct": float(threshold)}
    mode = "semantic" if retrieval_label.startswith("Semantic") else "lexical"
    try:
        with st.spinner("Calculating weekly costs and checking evidence…"):
            st.session_state.analysis = run_analysis(settings, mode, ANALYSIS_REVISION)
    except (OSError, ValueError, ImportError, RuntimeError) as exc:
        st.error(f"Analysis could not run: {exc}")
        st.info("For a fully offline numerical demo, select Lexical. Semantic mode needs its local model downloaded once.")

analysis = st.session_state.analysis
if analysis is None:
    st.info("Select your settings and click Run analysis to process the supplied shipment records.")
    st.stop()

rows, audit, cost = analysis["rows"], analysis["audit"], analysis["cost"]
frame = pd.DataFrame(rows)
summary = audit["summary"]
active_threshold = audit["configuration"]["anomaly_threshold_pct"]
active_mode = audit["retriever"]["mode"]
start_date = pd.Timestamp(frame.week_of.min()).strftime("%d %b %Y")
end_date = (pd.Timestamp(frame.week_of.max()) + pd.Timedelta(days=6)).strftime("%d %b %Y")
search_description = "Meaning-based evidence" if active_mode == "semantic" else "Keyword-based evidence"
st.markdown(
    f'<div class="analysis-meta"><span class="ready-pill">Analysis ready</span>'
    f'<span>{summary["route_count"]} routes · {start_date} – {end_date}</span>'
    f'<span>{active_threshold:g}% threshold</span><span>{search_description}</span></div>', unsafe_allow_html=True)

with st.container(key="summary"):
    cards = st.columns(4)
    cards[0].metric("Shipments analyzed", f"{summary['shipment_count']:,}")
    cards[1].metric("Route-weeks", f"{summary['route_week_count']:,}",
                    help="One route tracked during one Monday-to-Sunday week.")
    cards[2].metric("Needs review", summary["verdict_counts"].get("unexplained", 0),
                    help="Unusual rising-cost weeks without sufficient supporting context.")
    cards[3].metric("Explained rises", summary["verdict_counts"].get("justified", 0),
                    help="Unusual weeks with applicable, source-backed explanations.")

overview, explorer, questions, validation = st.tabs(["Review queue", "Route explorer", "Ask about findings", "Checks & cost"])

with overview:
    st.subheader("A closer look at the increases")
    st.markdown('<p class="section-description">Start with unexplained weeks, then explore the evidence behind each route.</p>', unsafe_allow_html=True)
    filter_cols = st.columns([2, 1, 1])
    routes = filter_cols[0].multiselect("Routes", sorted(frame.route.unique()), placeholder="All routes")
    status = filter_cols[1].selectbox("Verdict", ["Unexplained", "Justified", "All anomalies", "All rows"])
    kind = filter_cols[2].selectbox("Route type", ["All", "Short", "Medium", "Long"])
    selected = frame.copy()
    if routes:
        selected = selected[selected.route.isin(routes)]
    if status == "Unexplained":
        selected = selected[selected.verdict == "unexplained"]
    elif status == "Justified":
        selected = selected[selected.verdict == "justified"]
    elif status == "All anomalies":
        selected = selected[selected.anomaly_candidate]
    if kind != "All":
        selected = selected[selected.route_type == kind]
    selected = selected.sort_values(["vs_own_history_pct", "vs_similar_routes_pct"], ascending=False)
    show_columns = ["route", "week_of", "cost_per_tonne_km", "vs_own_history_pct",
                    "vs_similar_routes_pct", "matched_note_id"]
    display = selected[show_columns].copy()
    display.insert(2, "review_status", selected.verdict.map({
        "unexplained": "Needs review", "justified": "Explained", "normal": "Within range"}))
    st.caption(f"{len(display)} route-weeks · Largest increases versus history first")
    if display.empty:
        st.info("No route-weeks match these filters. Try another route or verdict.")
    else:
        st.dataframe(display.style.map(status_tone, subset=["review_status"]), hide_index=True,
                     width="stretch", row_height=44, height=430,
                     column_config={
                         "route": st.column_config.TextColumn("Route", width="medium"),
                         "week_of": st.column_config.TextColumn("Week beginning"),
                         "review_status": st.column_config.TextColumn("Status", width="small"),
                         "cost_per_tonne_km": st.column_config.NumberColumn("INR / tonne-km", format="%.2f"),
                         "vs_own_history_pct": st.column_config.NumberColumn("vs history (%)", format="%+.1f"),
                         "vs_similar_routes_pct": st.column_config.NumberColumn("vs peers (%)", format="%+.1f"),
                         "matched_note_id": st.column_config.TextColumn("Source note"),
                     })
    st.download_button("Download complete submission CSV", csv_text(rows), "analysis_output.csv", "text/csv")
    with st.expander("What is this comparison based on?"):
        comparison_basis("queue_basis")
        st.caption("A rising route becomes a candidate when it crosses the selected threshold against history or peers. Applicable context can explain the rise; otherwise it stays in the review queue.")

with explorer:
    st.subheader("Every route has a story")
    st.markdown('<p class="section-description">Compare the actual weekly rate with its own history and other routes of the same type.</p>', unsafe_allow_html=True)
    route = st.selectbox("Choose route", sorted(frame.route.unique()), key="explorer_route")
    route_frame = frame[frame.route == route].copy()
    chart = route_frame[["week_of", "cost_per_tonne_km", "history_average", "peer_average"]].copy()
    chart["week_of"] = pd.to_datetime(chart["week_of"])
    chart = chart.rename(columns={"cost_per_tonne_km": "Actual", "history_average": "Prior 8-week average",
                                  "peer_average": "Other routes this week"})
    with st.container(border=True):
        st.line_chart(chart, x="week_of", y=["Actual", "Prior 8-week average", "Other routes this week"],
                      color=["#d65322", "#365a7a", "#86a69d"], y_label="INR / tonne-km", height=340)
    candidate_weeks = route_frame[route_frame.anomaly_candidate].week_of.tolist()
    weeks = route_frame.week_of.tolist()
    default_week = weeks.index(candidate_weeks[0]) if candidate_weeks else len(weeks) - 1
    week = st.selectbox("Inspect week beginning Monday", weeks, index=default_week)
    row = next(item for item in rows if item["route"] == route and item["week_of"] == week)
    detail = st.columns(3)
    detail[0].metric("Cost / tonne-km", f"INR {row['cost_per_tonne_km']:.2f}")
    detail[1].metric("Prior weeks available", f"{row['history_weeks']} / 8")
    detail[2].metric("Peer routes available", row["peer_count"])
    st.markdown(f"**Verdict: {row['verdict'].capitalize()}** · Raw anomaly: {'Yes' if row['anomaly_candidate'] else 'No'}")
    st.write(row["reason"])
    if row["matched_note_id"]:
        note = next(item for item in audit["notes"] if item["note_id"] == row["matched_note_id"])
        with st.container(border=True, key="evidence_source"):
            st.caption("THE SUPPORTING EVIDENCE")
            st.markdown(f"**Source {note['note_id']} · {note['date']} · {note['applies_to']}**")
            st.write(note["note"])
            annotation = audit["annotations"][note["note_id"]]
            st.caption(f"Date interpretation: {annotation['interpretation']}")
    if row["evidence_checks"]:
        with st.expander("Inspect retrieved notes and evidence checks"):
            st.dataframe(pd.DataFrame(row["evidence_checks"]), hide_index=True, width="stretch")

with questions:
    st.subheader("Ask a question. Follow the evidence.")
    st.caption("Supported: one route, one optional month and year. Answers quote computed results and validated evidence.")
    question = st.text_input("Your question", "Why did Chennai-Bangalore get pricier in March 2025?")
    if st.button("Show findings", type="primary"):
        st.markdown(answer_question(question, rows))

with validation:
    st.subheader("The basis behind every flag")
    st.markdown('<p class="section-description">Transparent comparisons, applicable evidence, and checks you can inspect.</p>', unsafe_allow_html=True)
    comparison_basis("comparison_basis")
    st.caption(f"Current policy: a rise is required, with a {active_threshold:g}% threshold over history or peers. A note must pass route, date, cost-impact and coverage checks to explain it.")
    st.subheader("Validation & reproducibility")
    st.caption("Saved reports cover the submitted default configuration. Interactive settings may differ.")
    for filename, label in [("evaluation.json", "Saved evaluation report"), ("reproducibility.json", "Saved three-run report")]:
        path = ROOT / "results" / filename
        if path.exists():
            with st.expander(label):
                try:
                    st.json(json.loads(path.read_text(encoding="utf-8")), expanded=False)
                except (OSError, ValueError) as exc:
                    st.warning(f"Saved report could not load: {exc}")
    with st.expander("Configuration and threshold sensitivity"):
        st.json({"active_configuration": audit["configuration"],
                 "threshold_sensitivity": summary["threshold_sensitivity_candidate_counts"]}, expanded=True)
    st.subheader("What this run used")
    usage = st.columns(3)
    usage[0].metric("API spend", f"USD {cost['rough_api_cost_usd']:.2f}")
    usage[1].metric("Encoder input tokens", f"{cost['total_input_tokens']:,}")
    usage[2].metric("Analysis time", f"{cost['runtime_seconds']:.2f}s")
    st.caption("The embedding model runs locally. Explanations use verified source text; generative LLM calls are zero.")
    with st.expander("Full encoder and runtime log"):
        st.json(cost)
    with st.expander("All original context notes"):
        st.dataframe(pd.DataFrame(audit["notes"]), hide_index=True, width="stretch")

st.markdown('<div class="workspace-footer">FreightTiger internship case study · Monday–Sunday weeks · Source-backed explanations</div>',
            unsafe_allow_html=True)
