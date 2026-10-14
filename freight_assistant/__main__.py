import argparse
import json
import sys
from pathlib import Path

from .detection import Config
from .pipeline import ROOT, analyze, save_analysis


def main():
    parser = argparse.ArgumentParser(description="Weekly freight-cost monitoring with grounded note evidence")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "results")
    parser.add_argument("--config", type=Path, default=ROOT / "config.json")
    parser.add_argument("--retriever", choices=["semantic", "lexical"], default="semantic")
    parser.add_argument("--offline", action="store_true", help="Use only already downloaded model files")
    args = parser.parse_args()
    try:
        config = Config(**json.loads(args.config.read_text(encoding="utf-8")))
        rows, audit, cost = analyze(args.data_dir, config, args.retriever, offline=args.offline)
        output = save_analysis(args.output_dir, rows, audit, cost)
    except (ValueError, OSError, ImportError) as exc:
        print(f"Analysis failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(audit["summary"], indent=2))
    print(f"CSV: {output}")
    print(f"SHA256: {audit['output_sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
