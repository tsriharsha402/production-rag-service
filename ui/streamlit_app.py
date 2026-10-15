"""Streamlit front end for the RAG service.

Run:  API_URL=http://localhost:8000 streamlit run ui/streamlit_app.py
"""

from __future__ import annotations

import os

import requests
import streamlit as st

API_URL = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")
SAMPLE_QUESTIONS = [
    "When is the holiday change freeze?",
    "How fast do I need to acknowledge a SEV1 page?",
    "How much can I spend on courses and conferences?",
    "What is the company's 401k match?",
]

st.set_page_config(page_title="Handbook Assistant", page_icon="📚", layout="wide")


def fetch(method: str, path: str, **kwargs) -> requests.Response | None:
    try:
        return requests.request(method, f"{API_URL}{path}", timeout=90, **kwargs)
    except requests.RequestException as exc:
        st.error(f"Could not reach the API at {API_URL}: {exc}")
        return None


st.title("📚 Handbook Assistant")
st.write(
    "Ask a question about the (fictional) Northwind Labs engineering handbook. "
    "Every answer cites its sources, and the assistant says so when the handbook "
    "does not cover a question."
)


def send_feedback(answer_id: str, comment: str | None = None) -> None:
    choice = st.session_state.get(f"rating-{answer_id}")
    if choice is None:  # the vote was cleared
        return
    rating = "up" if choice == 1 else "down"
    payload = {"answer_id": answer_id, "rating": rating, "comment": comment or None}
    response = fetch("POST", "/v1/feedback", json=payload)
    if response is not None and response.ok:
        st.session_state.feedback_sent[answer_id] = "comment" if comment else rating
    elif response is not None:
        st.session_state.feedback_sent[answer_id] = f"error {response.status_code}"


def ask(question: str) -> tuple[dict | None, str | None]:
    """The answer body, or a message saying why there isn't one."""
    with st.spinner("Searching the handbook…"):
        response = fetch("POST", "/v1/query", json={"question": question})
    if response is None:
        return None, None  # fetch already showed the connection error
    if response.status_code == 429:
        return None, f"Rate limited. Try again in {response.headers.get('retry-after', '?')}s."
    if response.status_code == 503 and "budget" in response.text:
        return None, response.json()["detail"]
    if not response.ok:
        return None, f"The API returned {response.status_code}: {response.text}"
    return response.json(), None


st.session_state.setdefault("question", "")
st.session_state.setdefault("feedback_sent", {})

cols = st.columns(len(SAMPLE_QUESTIONS))
for col, sample in zip(cols, SAMPLE_QUESTIONS, strict=True):
    if col.button(sample, width="stretch"):
        st.session_state.question = sample

question = st.text_input("Your question", key="question", placeholder="Ask anything…")

# Ask once per question and keep the result: clicking a feedback button reruns the script,
# and re-asking would serve a new answer (with a new answer_id) instead of the one rated.
if question and st.session_state.get("asked") != question:
    st.session_state.asked = question
    st.session_state.body, st.session_state.problem = ask(question)

body = st.session_state.get("body") if question else None
if question and st.session_state.get("problem"):
    st.warning(st.session_state.problem)

if body is not None:
    if body["abstained"]:
        st.warning(body["answer"])
    else:
        st.success(body["answer"])

    usage = body["usage"]
    cost = "n/a" if usage["cost_usd"] is None else f"${usage['cost_usd']:.5f}"
    st.caption(
        f"{'⚡ cached · ' if body['cached'] else ''}{usage['latency_ms']:.0f} ms · "
        f"{usage['input_tokens']} in / {usage['output_tokens']} out tokens · {cost} · "
        f"`{usage['model']}`"
    )

    answer_id = body["answer_id"]
    st.feedback("thumbs", key=f"rating-{answer_id}", on_change=send_feedback, args=(answer_id,))
    sent = st.session_state.feedback_sent.get(answer_id)
    if sent == "down":
        with st.form(f"comment-{answer_id}", clear_on_submit=True, border=False):
            comment = st.text_input("What was wrong? (optional)", max_chars=1000)
            if st.form_submit_button("Send") and comment.strip():
                send_feedback(answer_id, comment.strip())
                st.rerun()
    if sent in ("up", "down", "comment"):
        st.caption("Thanks, your feedback was recorded.")
    elif sent:
        st.caption(f"Feedback wasn't recorded ({sent}).")

    if body["citations"]:
        st.subheader("Sources")
        for citation in body["citations"]:
            with st.expander(f"[{citation['ref']}] {citation['title']} › {citation['section']}"):
                st.markdown(f"> {citation['quote']}")

    with st.expander("Retrieval details"):
        st.dataframe(body["retrieved"], width="stretch", hide_index=True)

# Rendered last so the metrics include the question just asked.
with st.sidebar:
    st.header("Service health")
    health = fetch("GET", "/healthz")
    if health is not None and health.ok:
        info = health.json()
        st.caption(
            f"Model: `{info['model']}` · {info['chunks_indexed']} chunks indexed · "
            f"corpus `{info['corpus_version']}`"
        )
    metrics_response = fetch("GET", "/v1/metrics")
    if metrics_response is not None and metrics_response.ok:
        m = metrics_response.json()
        col1, col2 = st.columns(2)
        col1.metric("Requests", m["requests"])
        col2.metric("Cache hit rate", f"{m['cache_hit_rate']:.0%}")
        col1.metric("p50 latency", f"{m['latency_ms_p50']:.0f} ms")
        col2.metric("p95 latency", f"{m['latency_ms_p95']:.0f} ms")
        col1.metric("Abstentions", m["abstentions"])
        col2.metric("Errors", m["errors"])
        col1.metric("👍 / 👎", f"{m['feedback_up']} / {m['feedback_down']}")
        down_rate = m["thumbs_down_rate"]
        col2.metric("Thumbs-down rate", "–" if down_rate is None else f"{down_rate:.0%}")
        st.metric("Total spend", f"${m['total_cost_usd']:.4f}")
        st.metric("Avg cost / request", f"${m['avg_cost_per_request_usd']:.5f}")
