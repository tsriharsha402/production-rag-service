from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from rag_service.documents import Chunk
from rag_service.llm import (
    ABSTAIN_MESSAGE,
    REFUSAL_MESSAGE,
    AnthropicProvider,
    LLMError,
    OfflineProvider,
)

SOURCES = [
    Chunk("deploy#0", "deploy", "Deployment Process", "Deploy windows", "No Friday deploys."),
    Chunk("deploy#1", "deploy", "Deployment Process", "Canary", "Canary runs for 30 minutes."),
]


def _text(text, citations=None):
    return SimpleNamespace(type="text", text=text, citations=citations)


def _citation(index, quote):
    return SimpleNamespace(
        type="search_result_location", search_result_index=index, cited_text=quote
    )


def _response(content, stop_reason="end_turn"):
    usage = SimpleNamespace(
        input_tokens=1200,
        output_tokens=80,
        cache_read_input_tokens=None,
        cache_creation_input_tokens=None,
    )
    return SimpleNamespace(
        content=content, stop_reason=stop_reason, usage=usage, model="claude-opus-5-5"
    )


class FakeClient:
    def __init__(self, response=None, error=None):
        self.requests = []
        self._response = response
        self._error = error
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        if self._error:
            raise self._error
        return self._response


def test_request_uses_search_results_with_citations_and_refusal_fallback():
    provider = AnthropicProvider(client=FakeClient())
    request = provider.build_request("Can I deploy on Friday?", SOURCES)
    blocks = request["messages"][0]["content"]
    assert [b["type"] for b in blocks] == ["search_result", "search_result", "text"]
    assert blocks[0]["citations"] == {"enabled": True}
    assert blocks[0]["source"] == "deploy#0"
    assert blocks[0]["title"] == "Deployment Process > Deploy windows"
    assert request["model"] == "claude-opus-5-5"
    assert request["output_config"] == {"effort": "medium"}
    assert request["fallbacks"] == "default"
    assert request["betas"] == ["server-side-fallback-2026-07-01"]


def test_no_fallback_for_models_that_do_not_support_it():
    provider = AnthropicProvider(model="claude-haiku-4-5", client=FakeClient())
    request = provider.build_request("q", SOURCES)
    assert "fallbacks" not in request and "betas" not in request


def test_citations_are_mapped_to_sources_and_marked_inline():
    response = _response(
        [
            SimpleNamespace(type="thinking", thinking=""),
            _text("Not on Fridays", [_citation(0, "No Friday deploys.")]),
            _text(
                ", and canaries run for 30 minutes", [_citation(1, "Canary runs for 30 minutes.")]
            ),
            _text("."),
        ]
    )
    generation = AnthropicProvider(client=FakeClient(response)).generate("q", SOURCES)
    assert generation.text == "Not on Fridays [1], and canaries run for 30 minutes [2]."
    assert generation.citations == [(0, "No Friday deploys."), (1, "Canary runs for 30 minutes.")]
    assert (generation.input_tokens, generation.output_tokens) == (1200, 80)
    assert not generation.abstained


def test_abstention_is_detected():
    response = _response([_text(f"{ABSTAIN_MESSAGE} The documents do not cover this.")])
    generation = AnthropicProvider(client=FakeClient(response)).generate("q", SOURCES)
    assert generation.abstained
    assert generation.citations == []


def test_refusal_is_handled_without_reading_content():
    response = _response([], stop_reason="refusal")
    generation = AnthropicProvider(client=FakeClient(response)).generate("q", SOURCES)
    assert generation.refused
    assert generation.text == REFUSAL_MESSAGE


@pytest.mark.parametrize(
    ("status", "error_cls", "retryable"),
    [
        (429, anthropic.RateLimitError, True),
        (529, anthropic.APIStatusError, True),
        (400, anthropic.BadRequestError, False),
    ],
)
def test_api_errors_are_classified(status, error_cls, retryable):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    error = error_cls("boom", response=httpx2.Response(status, request=request), body=None)
    provider = AnthropicProvider(client=FakeClient(error=error))
    with pytest.raises(LLMError) as excinfo:
        provider.generate("q", SOURCES)
    assert excinfo.value.retryable is retryable


def test_offline_provider_extracts_best_sentence():
    generation = OfflineProvider().generate("How long does the canary run?", SOURCES)
    assert generation.text == "Canary runs for 30 minutes. [2]"
    assert generation.citations == [(1, "Canary runs for 30 minutes.")]


def test_offline_provider_abstains_without_overlap():
    generation = OfflineProvider().generate("What is the parental leave policy?", SOURCES)
    assert generation.abstained
