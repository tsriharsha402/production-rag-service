import importlib.util
import json
from pathlib import Path

from fastapi.testclient import TestClient

from rag_service.api import create_app
from rag_service.feedback import LocalFeedbackStore, RedisFeedbackStore, latest_per_answer

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "feedback_to_eval", ROOT / "evals/feedback_to_eval.py"
)
feedback_to_eval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(feedback_to_eval)


def ask(client, question="When is the holiday change freeze?"):
    response = client.post("/v1/query", json={"question": question})
    assert response.status_code == 200
    return response.json()


def test_every_response_gets_its_own_answer_id_including_cache_hits(app):
    client = TestClient(app)
    first, second = ask(client), ask(client)
    assert second["cached"] is True
    assert first["answer_id"] and second["answer_id"]
    assert first["answer_id"] != second["answer_id"]


def test_feedback_is_stored_with_what_the_service_actually_answered(settings, app):
    client = TestClient(app)
    answer = ask(client)
    response = client.post(
        "/v1/feedback",
        json={"answer_id": answer["answer_id"], "rating": "down", "comment": "Wrong year."},
    )
    assert response.status_code == 201
    assert response.json() == {"status": "recorded"}

    [entry] = LocalFeedbackStore(settings.feedback_path).entries()
    assert entry["question"] == "When is the holiday change freeze?"
    assert entry["answer"] == answer["answer"]
    assert entry["rating"] == "down"
    assert entry["comment"] == "Wrong year."
    assert entry["retrieved_docs"][0] == "deployment-process"
    assert entry["cited"][0]["doc_id"] == "deployment-process"
    assert entry["request_id"] and entry["feedback_at"]


def test_feedback_for_unknown_answer_is_rejected(app):
    response = TestClient(app).post("/v1/feedback", json={"answer_id": "nope", "rating": "up"})
    assert response.status_code == 404


def test_feedback_rejects_invalid_rating(app):
    client = TestClient(app)
    answer_id = ask(client)["answer_id"]
    response = client.post("/v1/feedback", json={"answer_id": answer_id, "rating": "meh"})
    assert response.status_code == 422


def test_feedback_counts_appear_in_metrics(app):
    client = TestClient(app)
    assert client.get("/v1/metrics").json()["thumbs_down_rate"] is None
    for rating in ("up", "up", "down"):
        client.post("/v1/feedback", json={"answer_id": ask(client)["answer_id"], "rating": rating})
    metrics = client.get("/v1/metrics").json()
    assert (metrics["feedback_up"], metrics["feedback_down"]) == (2, 1)
    assert metrics["thumbs_down_rate"] == 0.3333


def test_changing_a_vote_or_adding_a_comment_is_not_double_counted(app):
    client = TestClient(app)
    answer_id = ask(client)["answer_id"]
    for payload in (
        {"rating": "up"},
        {"rating": "down"},
        {"rating": "down", "comment": "Missed the hotfix rule."},
    ):
        client.post("/v1/feedback", json={"answer_id": answer_id, **payload})
    metrics = client.get("/v1/metrics").json()
    assert (metrics["feedback_up"], metrics["feedback_down"]) == (0, 1)


def test_feedback_has_its_own_rate_limit(settings, pipeline):
    from dataclasses import replace

    client = TestClient(create_app(replace(settings, rate_limit_per_minute=1), pipeline))
    answer_id = ask(client)["answer_id"]
    assert (
        client.post("/v1/feedback", json={"answer_id": answer_id, "rating": "up"}).status_code
        == 201
    )
    limited = client.post("/v1/feedback", json={"answer_id": answer_id, "rating": "down"})
    assert limited.status_code == 429


def test_answers_can_only_be_rated_within_the_window(tmp_path):
    now = [0.0]
    store = LocalFeedbackStore(tmp_path / "f.jsonl", answer_ttl_seconds=60, clock=lambda: now[0])
    store.remember({"answer_id": "a1"})
    assert store.lookup("a1") == {"answer_id": "a1"}
    now[0] = 61
    assert store.lookup("a1") is None


def test_remembered_answers_are_bounded(tmp_path):
    store = LocalFeedbackStore(tmp_path / "f.jsonl", max_answers=2)
    for answer_id in ("a1", "a2", "a3"):
        store.remember({"answer_id": answer_id})
    assert store.lookup("a1") is None
    assert store.lookup("a3") is not None


def test_feedback_file_survives_a_restart(tmp_path):
    path = tmp_path / "f.jsonl"
    LocalFeedbackStore(path).add({"answer_id": "a1", "rating": "up"})
    assert LocalFeedbackStore(path).entries() == [{"answer_id": "a1", "rating": "up"}]


def test_redis_store_shares_answers_and_feedback_across_replicas():
    class FakeRedis:
        def __init__(self):
            self.values, self.lists = {}, {}

        def setex(self, key, ttl, value):
            self.values[key] = value

        def get(self, key):
            return self.values.get(key)

        def rpush(self, key, value):
            self.lists.setdefault(key, []).append(value)

        def lrange(self, key, start, end):
            return self.lists.get(key, [])

    client = FakeRedis()
    replica_a, replica_b = RedisFeedbackStore(client), RedisFeedbackStore(client)
    replica_a.remember({"answer_id": "a1", "question": "q"})
    assert replica_b.lookup("a1") == {"answer_id": "a1", "question": "q"}
    assert not any(key.startswith("rag:answer:") for key in client.values)  # cache's prefix
    replica_b.add({"answer_id": "a1", "rating": "down"})
    assert replica_a.entries() == [{"answer_id": "a1", "rating": "down"}]


def test_latest_vote_per_answer_wins():
    votes = [
        {"answer_id": "a1", "rating": "up"},
        {"answer_id": "a2", "rating": "down"},
        {"answer_id": "a1", "rating": "down"},
    ]
    assert latest_per_answer(votes) == [votes[1], votes[2]]


def vote(answer_id, question, rating="down", abstained=False, retrieved=("travel",), comment=None):
    return {
        "answer_id": answer_id,
        "question": question,
        "rating": rating,
        "comment": comment,
        "abstained": abstained,
        "answer": "some answer",
        "retrieved_docs": list(retrieved),
        "cited": [],
    }


def test_draft_groups_thumbs_down_by_question_and_skips_covered_ones():
    feedback = [
        vote("a1", "Can I expense a taxi?", comment="Missed the cap"),
        vote("a2", "can i expense a taxi", comment="Still wrong"),
        vote("a3", "What's the 401k match?", abstained=True, retrieved=()),
        vote("a4", "How many PTO days?", rating="up"),
        vote("a5", "When is the change freeze?"),  # already in the dataset
        vote("a6", "Where do I park?"),
        vote("a6", "Where do I park?", rating="up"),  # changed their mind
    ]
    dataset = [{"id": "d1", "question": "When is the change freeze?"}]
    candidates, stats = feedback_to_eval.draft(feedback, dataset, existing=[])

    assert [c["question"] for c in candidates] == ["can i expense a taxi", "What's the 401k match?"]
    taxi, match = candidates
    assert taxi["answerable"] is None  # never guessed: a person decides
    assert taxi["review"]["thumbs_down"] == 2
    assert taxi["review"]["comments"] == ["Missed the cap", "Still wrong"]
    assert "rated down" in taxi["review"]["triage"]
    assert "nothing retrieved" in match["review"]["triage"]
    assert stats == {
        "votes": 6,
        "thumbs_down": 4,
        "questions_rated_down": 3,
        "already_covered": 1,
        "new_candidates": 2,
    }


def test_draft_does_not_duplicate_existing_candidates():
    existing = [{"id": "fb-1", "question": "Can I expense a taxi?", "answerable": True}]
    candidates, _ = feedback_to_eval.draft([vote("a1", "Can I expense a taxi")], [], existing)
    assert candidates == []


def test_promote_moves_only_reviewed_candidates():
    doc_ids = {"travel", "benefits"}
    candidates = [
        {
            "id": "fb-1",
            "question": "Taxi?",
            "answerable": True,
            "expected_doc": "travel",
            "expected_keywords": ["$50"],
            "review": {},
        },
        {
            "id": "fb-2",
            "question": "401k?",
            "answerable": False,
            "expected_doc": "benefits",
            "expected_keywords": ["x"],
            "review": {},
        },
        {"id": "fb-3", "question": "Unreviewed?", "answerable": None, "review": {}},
        {
            "id": "fb-4",
            "question": "Typo doc?",
            "answerable": True,
            "expected_doc": "travle",
            "expected_keywords": ["a"],
            "review": {},
        },
        {
            "id": "fb-5",
            "question": "No keywords?",
            "answerable": True,
            "expected_doc": "travel",
            "expected_keywords": [],
            "review": {},
        },
    ]
    ready, pending = feedback_to_eval.promote(candidates, dataset=[], doc_ids=doc_ids)

    assert ready == [
        {
            "id": "fb-1",
            "question": "Taxi?",
            "answerable": True,
            "expected_doc": "travel",
            "expected_keywords": ["$50"],
        },
        {
            "id": "fb-2",
            "question": "401k?",
            "answerable": False,
            "expected_doc": None,
            "expected_keywords": [],
        },
    ]
    assert [(c["id"], problem.split()[0]) for c, problem in pending] == [
        ("fb-3", "set"),
        ("fb-4", "expected_doc"),
        ("fb-5", "add"),
    ]


def test_promoted_cases_load_as_eval_cases(tmp_path):
    from rag_service.evaluation import load_cases

    path = tmp_path / "dataset.jsonl"
    ready, _ = feedback_to_eval.promote(
        [
            {
                "id": "fb-1",
                "question": "Taxi?",
                "answerable": True,
                "expected_doc": "travel",
                "expected_keywords": ["$50"],
                "review": {"triage": "..."},
            }
        ],
        dataset=[],
        doc_ids={"travel"},
    )
    feedback_to_eval.write_jsonl(path, ready)
    [case] = load_cases(path)
    assert case.expected_doc == "travel"
    assert json.loads(path.read_text())["id"] == "fb-1"
