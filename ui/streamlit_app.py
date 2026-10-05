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

if "question" not in st.session_state:
    st.session_state.question = ""

cols = st.columns(len(SAMPLE_QUESTIONS))
for col, sample in zip(cols, SAMPLE_QUESTIONS, strict=True):
    if col.button(sample, width="stretch"):
        st.session_state.question = sample

question = st.text_input("Your question", key="question", placeholder="Ask anything…")

if question:
    with st.spinner("Searching the handbook…"):
        response = fetch("POST", "/v1/query", json={"question": question})
    body = None
    if response is None:
        pass
    elif response.status_code == 429:
        st.warning(f"Rate limited. Try again in {response.headers.get('retry-after', '?')}s.")
    elif response.status_code == 503 and "budget" in response.text:
        st.warning(response.json()["detail"])
    elif not response.ok:
        st.error(f"The API returned {response.status_code}: {response.text}")
    else:
        body = response.json()

if question and body is not None:
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
        st.metric("Total spend", f"${m['total_cost_usd']:.4f}")
        st.metric("Avg cost / request", f"${m['avg_cost_per_request_usd']:.5f}")
