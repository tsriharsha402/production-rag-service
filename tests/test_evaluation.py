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
