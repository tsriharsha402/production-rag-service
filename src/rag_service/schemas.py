"""API request and response models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000, examples=["Can I deploy on a Friday?"])


class Citation(BaseModel):
    ref: int = Field(description="The [n] marker used in the answer text.")
    chunk_id: str
    doc_id: str
    title: str
    section: str
    quote: str = Field(description="Verbatim text from the source that supports the answer.")


class RetrievedChunk(BaseModel):
    ref: int
    chunk_id: str
    doc_id: str
    title: str
    section: str
    score: float


class Usage(BaseModel):
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float | None = Field(description="None when the model has no known price.")
    latency_ms: float


class QueryResponse(BaseModel):
    answer: str
    abstained: bool
    cached: bool
    citations: list[Citation]
    retrieved: list[RetrievedChunk]
    usage: Usage
