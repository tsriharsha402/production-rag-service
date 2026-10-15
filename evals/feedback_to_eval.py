"""Turn thumbs-down feedback into eval cases: draft candidates, review them, promote them.

    python evals/feedback_to_eval.py draft      # var/feedback.jsonl -> evals/candidates.jsonl
    python evals/feedback_to_eval.py draft --redis-url redis://localhost:6379/0
    python evals/feedback_to_eval.py promote    # reviewed candidates -> evals/dataset.jsonl

`draft` never guesses the expected answer. A thumbs down says something went wrong, not
what right looks like, so each candidate has `answerable: null` and a triage hint, and a
person fills in `answerable`, `expected_doc` and `expected_keywords` before `promote`
moves it into the dataset that gates CI.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from rag_service.cache import normalize_question
from rag_service.documents import load_documents
from rag_service.feedback import RedisFeedbackStore, latest_per_answer, read_jsonl

ROOT = Path(__file__).resolve().parent.parent
CASE_FIELDS = ("id", "question", "answerable", "expected_doc", "expected_keywords")


def triage_hint(entry: dict[str, Any]) -> str:
    if entry["abstained"] and not entry["retrieved_docs"]:
        return (
            "Abstained with nothing retrieved. If the handbook covers this, it's a retrieval "
            "miss (no shared vocabulary): set answerable=true. If not, the abstention was "
            "right: set answerable=false to lock it in, and flag the gap to the handbook owner."
        )
    if entry["abstained"]:
        return (
            "Abstained although documents were retrieved. If the answer is in them, generation "
            "was too cautious; if it's elsewhere in the handbook, retrieval missed it. If the "
            "handbook doesn't cover it, the abstention was right: set answerable=false."
        )
    return (
        "Answered and rated down. Check the cited quotes: wrong section means retrieval, "
        "right section but wrong answer means generation. If the handbook doesn't cover "
        "this, set answerable=false: the service should have abstained."
    )


def candidate_id(question: str) -> str:
    return "fb-" + hashlib.sha256(normalize_question(question).encode()).hexdigest()[:8]


def draft(
    feedback: list[dict[str, Any]], dataset: list[dict[str, Any]], existing: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """New candidates from thumbs-down votes. Skips questions already in the dataset or
    already drafted, so re-running never overwrites a reviewer's edits."""
    votes = latest_per_answer(feedback)
    known = {normalize_question(case["question"]) for case in dataset + existing}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for vote in votes:
        if vote["rating"] == "down":
            grouped.setdefault(normalize_question(vote["question"]), []).append(vote)

    candidates = []
    for normalized, group in grouped.items():
        if normalized in known:
            continue
        latest = group[-1]
        candidates.append(
            {
                "id": candidate_id(latest["question"]),
                "question": latest["question"],
                "answerable": None,
                "expected_doc": None,
                "expected_keywords": [],
                "review": {
                    "thumbs_down": len(group),
                    "comments": [v["comment"] for v in group if v.get("comment")],
                    "abstained": latest["abstained"],
                    "answer": latest["answer"],
                    "retrieved_docs": latest["retrieved_docs"],
                    "cited": latest["cited"],
                    "answer_ids": [v["answer_id"] for v in group],
                    "triage": triage_hint(latest),
                },
            }
        )
    # Most complained-about first: that's where review time pays off most.
    candidates.sort(key=lambda c: -c["review"]["thumbs_down"])
    stats = {
        "votes": len(votes),
        "thumbs_down": sum(v["rating"] == "down" for v in votes),
        "questions_rated_down": len(grouped),
        "already_covered": len(grouped) - len(candidates),
        "new_candidates": len(candidates),
    }
    return candidates, stats


def review_problem(candidate: dict[str, Any], doc_ids: set[str]) -> str | None:
    """Why a candidate can't be promoted yet, or None when it's ready."""
    if not isinstance(candidate.get("answerable"), bool):
        return "set answerable to true or false"
    if not candidate["answerable"]:
        return None
    if candidate.get("expected_doc") not in doc_ids:
        return f"expected_doc {candidate.get('expected_doc')!r} is not a handbook document"
    if not candidate.get("expected_keywords"):
        return "add expected_keywords: the facts a correct answer must contain"
    return None


def promote(
    candidates: list[dict[str, Any]], dataset: list[dict[str, Any]], doc_ids: set[str]
) -> tuple[list[dict[str, Any]], list[tuple[dict[str, Any], str]]]:
    """Split reviewed candidates into new dataset cases and those still needing review."""
    seen_ids = {case["id"] for case in dataset}
    seen_questions = {normalize_question(case["question"]) for case in dataset}
    ready, pending = [], []
    for candidate in candidates:
        problem = review_problem(candidate, doc_ids)
        if problem is None and (
            candidate["id"] in seen_ids
            or normalize_question(candidate["question"]) in seen_questions
        ):
            continue  # already promoted
        if problem is not None:
            pending.append((candidate, problem))
            continue
        case = {field: candidate[field] for field in CASE_FIELDS}
        if not case["answerable"]:
            case["expected_doc"], case["expected_keywords"] = None, []
        ready.append(case)
        seen_ids.add(case["id"])
        seen_questions.add(normalize_question(case["question"]))
    return ready, pending


def write_jsonl(path: Path, rows: list[dict[str, Any]], mode: str = "w") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open(mode, encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["draft", "promote"])
    parser.add_argument("--feedback", type=Path, default=ROOT / "var" / "feedback.jsonl")
    parser.add_argument("--redis-url", help="Read feedback from Redis instead of --feedback.")
    parser.add_argument("--dataset", type=Path, default=ROOT / "evals" / "dataset.jsonl")
    parser.add_argument("--candidates", type=Path, default=ROOT / "evals" / "candidates.jsonl")
    parser.add_argument("--corpus-dir", type=Path, default=ROOT / "data" / "handbook")
    args = parser.parse_args()

    dataset = read_jsonl(args.dataset)
    existing = read_jsonl(args.candidates)

    if args.command == "draft":
        feedback = (
            RedisFeedbackStore.from_url(args.redis_url).entries()
            if args.redis_url
            else read_jsonl(args.feedback)
        )
        candidates, stats = draft(feedback, dataset, existing)
        write_jsonl(args.candidates, candidates, mode="a")
        print(json.dumps(stats, indent=2))
        if candidates:
            print(f"Review {args.candidates}, then run: python evals/feedback_to_eval.py promote")
        return 0

    doc_ids = {doc.doc_id for doc in load_documents(args.corpus_dir)}
    ready, pending = promote(existing, dataset, doc_ids)
    write_jsonl(args.dataset, ready, mode="a")
    write_jsonl(args.candidates, [candidate for candidate, _ in pending])
    print(f"Promoted {len(ready)} case(s) to {args.dataset}.")
    for candidate, problem in pending:
        print(f"  still pending {candidate['id']} ({candidate['question'][:60]}): {problem}")
    if ready:
        print("Run `make eval` to see how the current service does on them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
