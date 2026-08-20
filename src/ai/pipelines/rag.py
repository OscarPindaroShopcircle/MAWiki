from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from haystack import Document, Pipeline, super_component
from haystack.components.converters import MultiFileConverter
from haystack.components.embedders.types import DocumentEmbedder, TextEmbedder
from haystack.components.joiners import DocumentJoiner as HaystackDocumentJoiner
from haystack.components.preprocessors import DocumentCleaner, DocumentSplitter
from haystack.components.retrievers.types import EmbeddingRetriever, TextRetriever
from haystack.components.writers import DocumentWriter
from haystack.core.component import Component
from haystack.dataclasses import ByteStream
from haystack.document_stores.types import DocumentStore, DuplicatePolicy

Source = str | Path | ByteStream


class DocumentJoiner(Protocol):
    def run(
        self, documents: Iterable[list[Document]], top_k: int | None = None
    ) -> dict[str, Any]: ...


class DocumentRanker(Protocol):
    def run(
        self, documents: list[Document], top_k: int | None = None
    ) -> dict[str, Any]: ...


class QueryDocumentRanker(Protocol):
    def run(
        self, *, query: str, documents: list[Document], top_k: int | None = None
    ) -> dict[str, Any]: ...


@super_component
class DocumentConverter:
    """Convert files or byte streams into Haystack documents."""

    def __init__(self, converter: Component | None = None) -> None:
        self.pipeline = Pipeline()
        self.pipeline.add_component(
            "converter", converter if converter is not None else MultiFileConverter()
        )
        self.input_mapping = {"sources": ["converter.sources"]}
        self.output_mapping = {"converter.documents": "documents"}

    if TYPE_CHECKING:

        def run(self, *, sources: list[Source]) -> dict[str, list[Document]]: ...


@super_component
class DocumentIndexer:
    """Clean, split, embed, and index existing Haystack documents."""

    def __init__(
        self,
        document_store: DocumentStore,
        document_embedder: DocumentEmbedder,
        *,
        cleaner: Component | None = None,
        splitter: Component | None = None,
        duplicate_policy: DuplicatePolicy = DuplicatePolicy.OVERWRITE,
    ) -> None:
        self.pipeline = Pipeline()
        self.pipeline.add_component(
            "cleaner", cleaner if cleaner is not None else DocumentCleaner()
        )
        self.pipeline.add_component(
            "splitter", splitter if splitter is not None else DocumentSplitter()
        )
        self.pipeline.add_component("embedder", document_embedder)
        self.pipeline.add_component(
            "writer",
            DocumentWriter(document_store=document_store, policy=duplicate_policy),
        )

        self.pipeline.connect("cleaner.documents", "splitter.documents")
        self.pipeline.connect("splitter.documents", "embedder.documents")
        self.pipeline.connect("embedder.documents", "writer.documents")

        self.input_mapping = {"documents": ["cleaner.documents"]}
        self.output_mapping = {"writer.documents_written": "documents_written"}

    if TYPE_CHECKING:

        def run(self, *, documents: list[Document]) -> dict[str, int]: ...


@super_component
class DocumentIngestionPipeline:
    """Convert files and index the resulting Haystack documents."""

    def __init__(
        self,
        document_store: DocumentStore,
        document_embedder: DocumentEmbedder,
        *,
        converter: Component | None = None,
        cleaner: Component | None = None,
        splitter: Component | None = None,
        duplicate_policy: DuplicatePolicy = DuplicatePolicy.OVERWRITE,
    ) -> None:
        self.pipeline = Pipeline()
        self.pipeline.add_component(
            "converter", converter if converter is not None else MultiFileConverter()
        )
        self.pipeline.add_component(
            "cleaner", cleaner if cleaner is not None else DocumentCleaner()
        )
        self.pipeline.add_component(
            "splitter", splitter if splitter is not None else DocumentSplitter()
        )
        self.pipeline.add_component("embedder", document_embedder)
        self.pipeline.add_component(
            "writer",
            DocumentWriter(document_store=document_store, policy=duplicate_policy),
        )

        self.pipeline.connect("converter.documents", "cleaner.documents")
        self.pipeline.connect("cleaner.documents", "splitter.documents")
        self.pipeline.connect("splitter.documents", "embedder.documents")
        self.pipeline.connect("embedder.documents", "writer.documents")

        self.input_mapping = {"sources": ["converter.sources"]}
        self.output_mapping = {"writer.documents_written": "documents_written"}

    if TYPE_CHECKING:

        def run(self, *, sources: list[Source]) -> dict[str, int]: ...


@super_component
class HybridRetriever:
    def __init__(
        self,
        text_embedder: TextEmbedder,
        embedding_retriever: EmbeddingRetriever,
        bm25_retriever: TextRetriever | None = None,
        *,
        joiner: DocumentJoiner | None = None,
        reranker: DocumentRanker | QueryDocumentRanker | None = None,
    ) -> None:
        self.pipeline = Pipeline()
        self.pipeline.add_component("embedder", text_embedder)
        self.pipeline.add_component("embedding_retriever", embedding_retriever)
        self.pipeline.connect(
            "embedder.embedding", "embedding_retriever.query_embedding"
        )

        output_component = "embedding_retriever"
        query_inputs = ["embedder.text"]
        if bm25_retriever is not None:
            self.pipeline.add_component("bm25_retriever", bm25_retriever)
            self.pipeline.add_component(
                "joiner", joiner if joiner is not None else HaystackDocumentJoiner()
            )
            self.pipeline.connect("embedding_retriever.documents", "joiner.documents")
            self.pipeline.connect("bm25_retriever.documents", "joiner.documents")
            output_component = "joiner"
            query_inputs.append("bm25_retriever.query")
        if reranker is not None:
            self.pipeline.add_component("reranker", reranker)
            self.pipeline.connect(f"{output_component}.documents", "reranker.documents")
            output_component = "reranker"
            if "query" in self.pipeline.inputs("reranker")["reranker"]:
                query_inputs.append("reranker.query")

        self.input_mapping = {"query": query_inputs}
        self.output_mapping = {f"{output_component}.documents": "documents"}

    if TYPE_CHECKING:

        def run(self, *, query: str) -> dict[str, list[Document]]: ...
