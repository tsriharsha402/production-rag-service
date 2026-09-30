from rag_service.documents import Document, chunk_document, corpus_version, load_documents


def test_load_documents_uses_first_heading_as_title(settings):
    docs = load_documents(settings.corpus_dir)
    titles = {doc.doc_id: doc.title for doc in docs}
    assert titles["oncall-policy"] == "On-Call Policy"
    assert len(docs) == 9


def test_chunks_stay_within_sections_and_have_unique_ids():
    doc = Document(
        doc_id="doc",
        title="Title",
        body=(
            "# Title\n\nIntro text.\n\n## Alpha\n\nFirst.\n\nSecond.\n\n"
            "## Beta\n\n- item one\n- item two\n"
        ),
    )
    chunks = chunk_document(doc)
    assert [c.section for c in chunks] == ["Title", "Alpha", "Beta"]
    assert chunks[1].text == "First.\nSecond."
    assert chunks[2].text == "- item one\n- item two"
    assert len({c.chunk_id for c in chunks}) == len(chunks)


def test_long_sections_are_split_under_the_size_limit():
    paragraph = "word " * 50
    body = "# T\n\n## S\n\n" + "\n\n".join([paragraph] * 10)
    chunks = chunk_document(Document("d", "T", body), max_chars=600)
    assert len(chunks) > 1
    assert all(len(c.text) <= 600 for c in chunks)


def test_corpus_version_changes_when_content_changes():
    a = [Document("d", "T", "one")]
    b = [Document("d", "T", "two")]
    assert corpus_version(a) != corpus_version(b)
    assert corpus_version(a) == corpus_version(list(a))
