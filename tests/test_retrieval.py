from rag_service.documents import Chunk
from rag_service.retrieval import BM25Index, tokenize


def _chunk(i: int, text: str) -> Chunk:
    return Chunk(chunk_id=f"c{i}", doc_id=f"d{i}", title="", section="", text=text)


def test_tokenize_drops_stopwords_and_folds_plurals():
    assert tokenize("What are the rollbacks for deploys?") == ["rollback", "deploy"]


def test_most_relevant_chunk_ranks_first():
    index = BM25Index(
        [
            _chunk(0, "Expense reports are due within 30 days."),
            _chunk(1, "Canary deploys roll back automatically when error rate exceeds 2%."),
            _chunk(2, "Vacation requests go through the HR portal."),
        ]
    )
    hits = index.search("when does a canary roll back?", top_k=2)
    assert hits[0].chunk.chunk_id == "c1"
    assert hits[0].score > 0


def test_no_overlap_returns_nothing():
    index = BM25Index([_chunk(0, "Expense reports are due within 30 days.")])
    assert index.search("quantum entanglement") == []
    assert index.search("the and of") == []


def test_handbook_retrieval(pipeline):
    hits = pipeline.index.search("How fast must I acknowledge a SEV1 page?", top_k=3)
    assert hits[0].chunk.doc_id == "oncall-policy"
