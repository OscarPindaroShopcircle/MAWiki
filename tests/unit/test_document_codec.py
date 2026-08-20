import pytest
from haystack import Document

from ai.document_codec import MarkdownDocumentCodec, MarkdownDocumentFormatError


def test_markdown_document_codec_round_trip() -> None:
    original = Document(
        id="converted-file-id",
        content="Heading\n\n---\n\nBody",
        meta={"source_file_id": "source-id", "output_index": 2, "page_number": 3},
    )

    restored = MarkdownDocumentCodec.loads(
        MarkdownDocumentCodec.dumps(original), document_id=original.id
    )

    assert restored.id == original.id
    assert restored.content == original.content
    assert restored.meta == original.meta


def test_markdown_document_codec_rejects_missing_front_matter() -> None:
    with pytest.raises(MarkdownDocumentFormatError, match="Missing YAML"):
        MarkdownDocumentCodec.loads(b"plain text")
