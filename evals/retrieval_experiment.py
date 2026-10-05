"""Compare retrieval settings on context recall and context size. No API key needed.

Context recall: for each answerable question, does the text sent to the model contain every
required fact? It's the ceiling on answer quality: a model can't cite what it never sees.

    python evals/retrieval_experiment.py
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from rag_service.api import build_pipeline
from rag_service.config import Settings
from rag_service.documents import Chunk
from rag_service.evaluation import load_cases

ROOT = Path(__file__).resolve().parent.parent
MIN_SCORE = Settings.min_retrieval_score


def main() -> int:
    logging.disable(logging.CRITICAL)
    pipeline = build_pipeline(
        Settings(llm_provider="offline", corpus_dir=ROOT / "data" / "handbook")
    )
    index = pipeline.index
    by_doc: dict[str, list[Chunk]] = {}
    for chunk in index.chunks:
        by_doc.setdefault(chunk.doc_id, []).append(chunk)

    def top_chunks(k: int) -> Callable[[str], list[Chunk]]:
        return lambda q: [h.chunk for h in index.search(q, k) if h.score >= MIN_SCORE]

    def top_documents(n: int, k: int = 4) -> Callable[[str], list[Chunk]]:
        # Parent-document retrieval: rank by chunk, then send every section of the top n docs.
        def retrieve(q: str) -> list[Chunk]:
            docs: list[str] = []
            for hit in index.search(q, k):
                if hit.score >= MIN_SCORE and hit.chunk.doc_id not in docs:
                    docs.append(hit.chunk.doc_id)
            return [chunk for doc in docs[:n] for chunk in by_doc[doc]]

        return retrieve

    variants: dict[str, Callable[[str], list[Chunk]]] = {
        **{f"top {k} chunks": top_chunks(k) for k in (4, 6, 8, 10, 12)},
        **{f"top {n} whole document(s)": top_documents(n) for n in (1, 2, 3)},
    }
    cases = [c for c in load_cases(ROOT / "evals" / "dataset.jsonl") if c.answerable]

    lines = [
        "# Retrieval experiment",
        "",
        f"{len(cases)} answerable questions from `evals/dataset.jsonl`. Context size is estimated "
        "at 4 characters per token.",
        "",
        "| Variant | Context recall | Avg context tokens | Questions still missing the answer |",
        "|---|---|---|---|",
    ]
    for name, retrieve in variants.items():
        found, sizes, missing = 0, [], []
        for case in cases:
            context = retrieve(case.question)
            text = " ".join(chunk.text for chunk in context).lower()
            sizes.append(sum(len(chunk.text) for chunk in context) / 4)
            if all(kw.lower() in text for kw in case.expected_keywords):
                found += 1
            else:
                missing.append(case.id)
        lines.append(
            f"| {name} | {found}/{len(cases)} ({found / len(cases):.1%}) "
            f"| {sum(sizes) / len(sizes):.0f} | {', '.join(missing) or 'none'} |"
        )
    report = "\n".join(lines) + "\n"
    out = ROOT / "evals" / "results" / "retrieval-experiment.md"
    out.write_text(report)
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
