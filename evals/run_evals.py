"""Run the evaluation suite and fail if quality drops below the agreed thresholds.

Examples:
    python evals/run_evals.py                          # offline baseline, no API key
    python evals/run_evals.py --provider anthropic     # Claude (needs ANTHROPIC_API_KEY)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rag_service.api import build_pipeline
from rag_service.cache import NullCache
from rag_service.config import Settings
from rag_service.evaluation import load_cases, render_markdown, run_case, summarize

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--provider", default="offline", choices=["offline", "anthropic"])
    parser.add_argument("--model", default=Settings.model)
    parser.add_argument("--effort", default=Settings.effort)
    parser.add_argument("--dataset", type=Path, default=ROOT / "evals" / "dataset.jsonl")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "evals" / "results")
    parser.add_argument("--min-hit-at-k", type=float, default=0.0)
    parser.add_argument("--min-keyword-recall", type=float, default=0.0)
    parser.add_argument("--min-abstention-accuracy", type=float, default=0.0)
    args = parser.parse_args()

    settings = Settings(
        llm_provider=args.provider,
        model=args.model,
        effort=args.effort,
        corpus_dir=ROOT / "data" / "handbook",
        cache_backend="none",
    )
    pipeline = build_pipeline(settings)
    pipeline.cache = NullCache()

    cases = load_cases(args.dataset)
    results = []
    for case in cases:
        result = run_case(pipeline, case)
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] {case.id}: {result.answer[:90]}")
        results.append(result)

    summary = summarize(results)
    label = args.provider if args.provider == "offline" else f"{args.model} (effort={args.effort})"
    stem = "offline" if args.provider == "offline" else args.model
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / f"{stem}.md").write_text(render_markdown(summary, results, label))
    (args.out_dir / f"{stem}.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))

    gates = {
        "retrieval_hit_at_k": args.min_hit_at_k,
        "answer_keyword_recall": args.min_keyword_recall,
        "abstention_accuracy": args.min_abstention_accuracy,
    }
    failures = [
        f"{name} {summary[name]:.3f} < {floor:.3f}"
        for name, floor in gates.items()
        if summary[name] < floor
    ]
    if failures:
        print("Quality gate FAILED: " + "; ".join(failures), file=sys.stderr)
        return 1
    print("Quality gate passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
