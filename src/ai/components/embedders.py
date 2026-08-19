from __future__ import annotations

from dataclasses import replace
from typing import Any

from haystack import Document, component
from model2vec import StaticModel  # noqa: PLC0415


@component
class Model2VecTextEmbedder:
    """Text embedder wrapping model2vec.StaticModel for single-query embedding."""

    def __init__(
        self,
        model_name: str = "minishlab/M2V_base_output",
    ) -> None:
        self.model_name = model_name
        self.model: Any = None

    def warm_up(self) -> None:
        if self.model is None:
            self.model = StaticModel.from_pretrained(self.model_name)

    @component.output_types(embedding=list[float])
    def run(self, text: str) -> dict[str, list[float]]:
        if self.model is None:
            self.warm_up()
        embedding = self.model.encode(text)
        return {"embedding": embedding.tolist()}


@component
class Model2VecDocumentEmbedder:
    """Document embedder wrapping model2vec.StaticModel for batch embedding."""

    def __init__(
        self,
        model_name: str = "minishlab/M2V_base_output",
    ) -> None:
        self.model_name = model_name
        self.model: Any = None

    def warm_up(self) -> None:
        if self.model is None:
            self.model = StaticModel.from_pretrained(self.model_name)

    @component.output_types(documents=list[Document])
    def run(self, documents: list[Document]) -> dict[str, list[Document]]:
        if self.model is None:
            self.warm_up()
        texts = [doc.content or "" for doc in documents]
        embeddings = self.model.encode(texts)
        # Clone instead of mutating: other references to the same Document
        # instance (e.g. other pipeline branches) must not see the embedding.
        new_documents = [
            replace(doc, embedding=emb.tolist())
            for doc, emb in zip(documents, embeddings, strict=True)
        ]
        return {"documents": new_documents}
