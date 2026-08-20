from dataclasses import replace

from haystack import Document, component
from haystack.components.retrievers import (
    InMemoryBM25Retriever,
    InMemoryEmbeddingRetriever,
)
from haystack.document_stores.in_memory import InMemoryDocumentStore

from ai.pipelines.rag import (
    DocumentConverter,
    DocumentIndexer,
    DocumentIngestionPipeline,
    HybridRetriever,
)


@component
class TextConverter:
    @component.output_types(documents=list[Document])
    def run(self, sources: list[str]) -> dict[str, list[Document]]:
        return {"documents": [Document(content=source) for source in sources]}


@component
class DocumentEmbedder:
    @component.output_types(documents=list[Document])
    def run(self, documents: list[Document]) -> dict[str, list[Document]]:
        return {
            "documents": [
                replace(document, embedding=[1.0, 0.0]) for document in documents
            ]
        }


@component
class TextEmbedder:
    @component.output_types(embedding=list[float])
    def run(self, text: str) -> dict[str, list[float]]:
        return {"embedding": [1.0, 0.0]}


@component
class QueryRanker:
    def __init__(self) -> None:
        self.query: str | None = None

    @component.output_types(documents=list[Document])
    def run(
        self,
        *,
        query: str,
        documents: list[Document],
        top_k: int | None = None,
    ) -> dict[str, list[Document]]:
        self.query = query
        return {"documents": documents[:top_k] if top_k else documents}


async def test_rag_supercomponents_convert_index_and_retrieve_documents() -> None:
    converter = DocumentConverter(TextConverter())
    conversion_result = await converter.run_async(sources=["alpha beta"])
    store = InMemoryDocumentStore(embedding_similarity_function="cosine")
    indexer = DocumentIndexer(store, DocumentEmbedder())

    indexing_result = await indexer.run_async(documents=conversion_result["documents"])

    assert indexing_result == {"documents_written": 1}
    assert converter.input_mapping == {"sources": ["converter.sources"]}
    assert indexer.input_mapping == {"documents": ["cleaner.documents"]}

    retriever = HybridRetriever(
        TextEmbedder(),
        InMemoryEmbeddingRetriever(store),
        InMemoryBM25Retriever(store),
    )

    retrieval_result = await retriever.run_async(query="alpha")

    assert retrieval_result["documents"][0].content == "alpha beta"
    assert retriever.input_mapping == {
        "query": ["embedder.text", "bm25_retriever.query"]
    }
    assert retriever.output_mapping == {"joiner.documents": "documents"}


async def test_document_ingestion_pipeline_combines_conversion_and_indexing() -> None:
    store = InMemoryDocumentStore(embedding_similarity_function="cosine")
    ingestion = DocumentIngestionPipeline(
        store, DocumentEmbedder(), converter=TextConverter()
    )

    result = await ingestion.run_async(sources=["alpha"])

    assert result == {"documents_written": 1}
    assert store.count_documents() == 1


def test_hybrid_retriever_forwards_query_to_reranker() -> None:
    store = InMemoryDocumentStore(embedding_similarity_function="cosine")
    store.write_documents([Document(content="alpha", embedding=[1.0, 0.0])])
    ranker = QueryRanker()
    retriever = HybridRetriever(
        TextEmbedder(),
        InMemoryEmbeddingRetriever(store),
        InMemoryBM25Retriever(store),
        reranker=ranker,
    )

    result = retriever.run(query="alpha")

    assert ranker.query == "alpha"
    assert result["documents"][0].content == "alpha"
    assert retriever.output_mapping == {"reranker.documents": "documents"}


def test_hybrid_retriever_supports_semantic_only_search() -> None:
    store = InMemoryDocumentStore(embedding_similarity_function="cosine")
    store.write_documents([Document(content="alpha", embedding=[1.0, 0.0])])
    retriever = HybridRetriever(TextEmbedder(), InMemoryEmbeddingRetriever(store))

    result = retriever.run(query="alpha")

    assert result["documents"][0].content == "alpha"
    assert retriever.input_mapping == {"query": ["embedder.text"]}
    assert retriever.output_mapping == {"embedding_retriever.documents": "documents"}
