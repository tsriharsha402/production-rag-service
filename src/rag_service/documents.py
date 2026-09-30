"""Loading markdown documents and splitting them into retrievable chunks."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

_HEADING = re.compile(r"^(#{1,3})\s+(.*)$")


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    title: str
    section: str
    text: str


@dataclass(frozen=True)
class Document:
    doc_id: str
    title: str
    body: str


def load_documents(corpus_dir: Path) -> list[Document]:
    """Load every ``*.md`` file in ``corpus_dir``. The first ``#`` heading is the title."""
    docs = []
    for path in sorted(corpus_dir.glob("*.md")):
        body = path.read_text(encoding="utf-8")
        title = path.stem.replace("-", " ").title()
        for line in body.splitlines():
            match = _HEADING.match(line)
            if match and len(match.group(1)) == 1:
                title = match.group(2).strip()
                break
        docs.append(Document(doc_id=path.stem, title=title, body=body))
    if not docs:
        raise FileNotFoundError(f"No markdown documents found in {corpus_dir}")
    return docs


def corpus_version(docs: list[Document]) -> str:
    """Short content hash. Part of the cache key, so editing a document invalidates answers."""
    digest = hashlib.sha256()
    for doc in docs:
        digest.update(doc.doc_id.encode())
        digest.update(doc.body.encode())
    return digest.hexdigest()[:12]


def chunk_document(doc: Document, max_chars: int = 900) -> list[Chunk]:
    """Split a document by section, then pack paragraphs into chunks of at most ``max_chars``.

    Chunks never cross a section boundary, so every chunk can be cited with a
    meaningful "Title > Section" label.
    """
    sections: list[tuple[str, list[str]]] = []
    current_heading = doc.title
    paragraphs: list[str] = []
    buffer: list[str] = []

    def flush_paragraph() -> None:
        text = " ".join(line.strip() for line in buffer).strip()
        if text:
            paragraphs.append(text)
        buffer.clear()

    for line in doc.body.splitlines():
        match = _HEADING.match(line)
        if match:
            flush_paragraph()
            if paragraphs:
                sections.append((current_heading, paragraphs))
                paragraphs = []
            if len(match.group(1)) > 1:
                current_heading = match.group(2).strip()
        elif not line.strip():
            flush_paragraph()
        elif line.lstrip().startswith(("- ", "* ", "|")) or re.match(r"^\s*\d+\.\s", line):
            # Keep list items and table rows as separate lines inside one paragraph.
            flush_paragraph()
            paragraphs.append(line.strip())
        else:
            buffer.append(line)
    flush_paragraph()
    if paragraphs:
        sections.append((current_heading, paragraphs))

    chunks: list[Chunk] = []
    for heading, paras in sections:
        packed: list[str] = []
        size = 0
        for para in paras:
            if packed and size + len(para) > max_chars:
                chunks.append(_make_chunk(doc, heading, packed, len(chunks)))
                packed, size = [], 0
            packed.append(para)
            size += len(para) + 1
        if packed:
            chunks.append(_make_chunk(doc, heading, packed, len(chunks)))
    return chunks


def _make_chunk(doc: Document, heading: str, paras: list[str], n: int) -> Chunk:
    return Chunk(
        chunk_id=f"{doc.doc_id}#{n}",
        doc_id=doc.doc_id,
        title=doc.title,
        section=heading,
        text="\n".join(paras),
    )
