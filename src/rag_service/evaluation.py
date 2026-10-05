"""Offline evaluation of retrieval, answer quality, abstention, cost and latency."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rag_service.metrics import percentile
from rag_service.pipeline import RAGPipeline


@dataclass
class EvalCase:
    id: str
    question: str
    answerable: bool
    expected_doc: str | None = None
    expected_keywords: list[str] = field(default_factory=list)


@dataclass
class CaseResult:
    case: EvalCase
    answer: str
    abstained: bool
    retrieved_docs: list[str]
    cited_docs: list[str]
    keyword_recall: float
    cost_usd: float
    latency_ms: float
    # Whether the context sent to the model contained every required fact. Stricter than
    # hit@k, which only checks the document: the right document's wrong section passes hit@k
    # but leaves the model nothing to answer from.
    context_has_answer: bool = False

    @property
    def rank(self) -> int | None:
        """1-based rank of the first chunk from the expected document, if retrieved."""
        for position, doc in enumerate(self.retrieved_docs, start=1):
            if doc == self.case.expected_doc:
                return position
        return None

    @property
    def passed(self) -> bool:
        if not self.case.answerable:
            return self.abstained
        return (
            not self.abstained
            and self.keyword_recall == 1.0
            and self.case.expected_doc in self.cited_docs
        )


def load_cases(path: Path) -> list[EvalCase]:
    with path.open(encoding="utf-8") as handle:
        return [EvalCase(**json.loads(line)) for line in handle if line.strip()]


def run_case(pipeline: RAGPipeline, case: EvalCase) -> CaseResult:
    response = pipeline.answer(case.question)
    answer_lower = response.answer.lower()
    found = [kw for kw in case.expected_keywords if kw.lower() in answer_lower]
    texts = {chunk.chunk_id: chunk.text for chunk in pipeline.index.chunks}
    context = " ".join(texts.get(r.chunk_id, "") for r in response.retrieved).lower()
    return CaseResult(
        case=case,
        answer=response.answer,
        abstained=response.abstained,
        retrieved_docs=[chunk.doc_id for chunk in response.retrieved],
        cited_docs=sorted({citation.doc_id for citation in response.citations}),
        keyword_recall=len(found) / len(case.expected_keywords) if case.expected_keywords else 1.0,
        cost_usd=response.usage.cost_usd or 0.0,
        latency_ms=response.usage.latency_ms,
        context_has_answer=bool(case.expected_keywords)
        and all(kw.lower() in context for kw in case.expected_keywords),
    )


def summarize(results: list[CaseResult]) -> dict[str, Any]:
    answerable = [r for r in results if r.case.answerable]
    unanswerable = [r for r in results if not r.case.answerable]

    def mean(values: list[float]) -> float:
        return round(sum(values) / len(values), 4) if values else 0.0

    ranks = [r.rank for r in answerable]
    latencies = [r.latency_ms for r in results]
    return {
        "cases": len(results),
        "answerable": len(answerable),
        "unanswerable": len(unanswerable),
        "retrieval_hit_at_1": mean([1.0 if rank == 1 else 0.0 for rank in ranks]),
        "retrieval_hit_at_k": mean([1.0 if rank else 0.0 for rank in ranks]),
        "retrieval_mrr": mean([1.0 / rank if rank else 0.0 for rank in ranks]),
        "retrieval_context_recall": mean(
            [1.0 if r.context_has_answer else 0.0 for r in answerable]
        ),
        "answer_keyword_recall": mean([r.keyword_recall for r in answerable]),
        "citation_accuracy": mean(
            [1.0 if r.case.expected_doc in r.cited_docs else 0.0 for r in answerable]
        ),
        "false_abstention_rate": mean([1.0 if r.abstained else 0.0 for r in answerable]),
        "abstention_accuracy": mean([1.0 if r.abstained else 0.0 for r in unanswerable]),
        "pass_rate": mean([1.0 if r.passed else 0.0 for r in results]),
        "total_cost_usd": round(sum(r.cost_usd for r in results), 6),
        "avg_cost_per_question_usd": round(
            sum(r.cost_usd for r in results) / max(len(results), 1), 6
        ),
        "latency_ms_p50": round(percentile(latencies, 50), 1),
        "latency_ms_p95": round(percentile(latencies, 95), 1),
    }


def render_markdown(summary: dict[str, Any], results: list[CaseResult], label: str) -> str:
    def pct(key: str) -> str:
        return f"{summary[key] * 100:.1f}%"

    lines = [
        f"# Evaluation results: {label}",
        "",
        f"{summary['cases']} questions ({summary['answerable']} answerable, "
        f"{summary['unanswerable']} deliberately unanswerable).",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Retrieval hit@1 | {pct('retrieval_hit_at_1')} |",
        f"| Retrieval hit@k | {pct('retrieval_hit_at_k')} |",
        f"| Retrieval MRR | {summary['retrieval_mrr']:.3f} |",
        f"| Context recall (answer in retrieved text) | {pct('retrieval_context_recall')} |",
        f"| Answer keyword recall | {pct('answer_keyword_recall')} |",
        f"| Citation accuracy | {pct('citation_accuracy')} |",
        f"| False abstention rate | {pct('false_abstention_rate')} |",
        f"| Abstention accuracy (unanswerable) | {pct('abstention_accuracy')} |",
        f"| Overall pass rate | {pct('pass_rate')} |",
        f"| Total cost | ${summary['total_cost_usd']:.4f} |",
        f"| Avg cost per question | ${summary['avg_cost_per_question_usd']:.5f} |",
        f"| Latency p50 / p95 | {summary['latency_ms_p50']} ms / {summary['latency_ms_p95']} ms |",
        "",
        "## Failed cases",
        "",
    ]
    failed = [r for r in results if not r.passed]
    if not failed:
        lines.append("None.")
    else:
        lines += ["| Case | Question | Problem |", "|---|---|---|"]
        for r in failed:
            if not r.case.answerable:
                problem = "answered a question the documents cannot answer"
            elif r.abstained:
                problem = "abstained on an answerable question"
            else:
                issues = []
                if r.rank is None:
                    issues.append("expected document not retrieved")
                if r.case.expected_doc not in r.cited_docs:
                    issues.append("expected document not cited")
                if r.keyword_recall < 1.0:
                    issues.append(f"keyword recall {r.keyword_recall:.0%}")
                problem = ", ".join(issues)
            lines.append(f"| {r.case.id} | {r.case.question} | {problem} |")
    return "\n".join(lines) + "\n"
