from pathlib import Path

from rag_service.cache import NullCache
from rag_service.evaluation import load_cases, render_markdown, run_case, summarize

DATASET = Path(__file__).resolve().parent.parent / "evals" / "dataset.jsonl"


def test_dataset_is_well_formed(settings):
    cases = load_cases(DATASET)
    doc_ids = {path.stem for path in settings.corpus_dir.glob("*.md")}
    assert len({case.id for case in cases}) == len(cases)
    for case in cases:
        if case.answerable:
            assert case.expected_doc in doc_ids, case.id
            assert case.expected_keywords, case.id


def test_eval_run_produces_summary_and_report(pipeline):
    pipeline.cache = NullCache()
    cases = load_cases(DATASET)[:5] + [c for c in load_cases(DATASET) if not c.answerable][:1]
    results = [run_case(pipeline, case) for case in cases]
    summary = summarize(results)
    assert summary["cases"] == 6
    assert 0.0 <= summary["retrieval_mrr"] <= 1.0
    report = render_markdown(summary, results, "offline")
    assert "Retrieval hit@1" in report


def test_context_recall_detects_right_document_wrong_section(pipeline):
    from dataclasses import replace

    pipeline.cache = NullCache()
    case = next(c for c in load_cases(DATASET) if c.id == "incident-01")
    # With 4 results the incident document is retrieved but not its "Severity levels" section.
    pipeline.top_k = 4
    narrow = run_case(pipeline, case)
    assert "incident-response" in narrow.retrieved_docs
    assert not narrow.context_has_answer
    pipeline.top_k = 8
    assert run_case(pipeline, replace(case)).context_has_answer
    summary = summarize([narrow])
    assert summary["retrieval_context_recall"] == 0.0


def test_default_top_k_is_eight():
    from rag_service.config import Settings

    assert Settings().top_k == 8
