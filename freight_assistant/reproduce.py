"""Run three actual fresh processes; never reuse saved analysis output."""

import argparse
import json
from pathlib import Path
import subprocess
import sys

from .pipeline import ROOT
from .reporting import file_hash, write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--retriever", choices=["semantic", "lexical"], default="semantic")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    runs = []
    for number in range(1, 4):
        directory = ROOT / "results/repro_runs" / str(number)
        command = [sys.executable, "-m", "freight_assistant", "--retriever", args.retriever,
                   "--output-dir", str(directory)]
        if args.offline:
            command.append("--offline")
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        if completed.returncode:
            raise RuntimeError(f"Fresh-process run {number} failed:\n{completed.stderr}")
        audit = json.loads((directory / "audit.json").read_text(encoding="utf-8"))
        runs.append({"run": number, "csv_sha256": file_hash(directory / "analysis_output.csv"),
                     "audit_sha256": file_hash(directory / "audit.json"),
                     "input_sha256": audit["input_sha256"], "configuration": audit["configuration"],
                     "summary": audit["summary"]})
        print(f"Run {number}: {runs[-1]['csv_sha256']}", flush=True)
    identical = len({run["csv_sha256"] for run in runs}) == 1
    audit_identical = len({run["audit_sha256"] for run in runs}) == 1
    report = {"fresh_processes": 3, "retriever": args.retriever,
              "identical_csv_bytes": identical, "identical_full_audit": audit_identical,
              "method": "Three CLI subprocesses recompute all metrics, embeddings for queries, evidence checks and exports. Model weights/document vectors may be cached; analysis results are not cached.",
              "runs": runs}
    write_json(ROOT / "results/reproducibility.json", report)
    return 0 if identical and audit_identical else 1


if __name__ == "__main__":
    raise SystemExit(main())
