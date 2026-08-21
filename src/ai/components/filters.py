from __future__ import annotations

from haystack import Document, component


@component
class ScoreThresholdFilter:
    """Drops documents whose `score` is below a fixed threshold."""

    def __init__(self, threshold: float) -> None:
        self.threshold = threshold

    @component.output_types(documents=list[Document])
    def run(self, documents: list[Document]) -> dict[str, list[Document]]:
        filtered = [
            doc
            for doc in documents
            if doc.score is not None and doc.score >= self.threshold
        ]
        return {"documents": filtered}
