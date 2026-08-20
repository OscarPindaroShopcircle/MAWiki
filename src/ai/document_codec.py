from typing import Any

import yaml
from haystack import Document


class MarkdownDocumentFormatError(ValueError):
    pass


class MarkdownDocumentCodec:
    @staticmethod
    def dumps(document: Document) -> bytes:
        metadata = yaml.safe_dump(
            document.meta,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=True,
        ).rstrip()
        return f"---\n{metadata}\n---\n\n{document.content or ''}".encode()

    @staticmethod
    def loads(data: bytes, document_id: str | None = None) -> Document:
        text = data.decode()
        lines = text.splitlines(keepends=True)
        if not lines or lines[0].strip() != "---":
            raise MarkdownDocumentFormatError("Missing YAML front matter")
        boundary = next(
            (
                index
                for index, line in enumerate(lines[1:], start=1)
                if line.strip() == "---"
            ),
            None,
        )
        if boundary is None:
            raise MarkdownDocumentFormatError("Unclosed YAML front matter")
        metadata: Any = yaml.safe_load("".join(lines[1:boundary])) or {}
        if not isinstance(metadata, dict):
            raise MarkdownDocumentFormatError("YAML front matter must be a dictionary")
        content = "".join(lines[boundary + 1 :])
        if content.startswith("\n"):
            content = content[1:]
        return Document(id=document_id, content=content, meta=metadata)
