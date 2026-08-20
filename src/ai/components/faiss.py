from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

from haystack import Document, component
from haystack.components.embedders.types import DocumentEmbedder, TextEmbedder
from haystack.components.preprocessors import DocumentSplitter
from haystack.document_stores.types import DuplicatePolicy
from haystack_integrations.components.retrievers.faiss import FAISSEmbeddingRetriever
from haystack_integrations.document_stores.faiss import FAISSDocumentStore


@component
class FaissIndexer:
    def __init__(
        self,
        document_embedder: DocumentEmbedder,
        split_length: int = 200,
        split_overlap: int = 20,
    ) -> None:
        self.document_embedder = document_embedder
        self.splitter = DocumentSplitter(
            split_by="word",
            split_length=split_length,
            split_overlap=split_overlap,
        )
        self.splitter.warm_up()

    @component.output_types(archive=bytes, documents_indexed=int)
    def run(self, documents: list[Document]) -> dict[str, bytes | int]:
        chunks = self.splitter.run(documents=documents)["documents"]
        chunks = self.document_embedder.run(documents=chunks)["documents"]
        if not chunks or chunks[0].embedding is None:
            raise ValueError("No embedded documents to index")
        document_store = FAISSDocumentStore(
            index_string="Flat", embedding_dim=len(chunks[0].embedding)
        )
        document_store.write_documents(chunks, policy=DuplicatePolicy.OVERWRITE)
        with TemporaryDirectory() as directory:
            index_path = Path(directory) / "index"
            document_store.save(index_path)
            output = BytesIO()
            with ZipFile(output, "w", ZIP_DEFLATED) as archive:
                archive.write(index_path.with_suffix(".faiss"), "index.faiss")
                archive.write(index_path.with_suffix(".json"), "index.json")
        return {"archive": output.getvalue(), "documents_indexed": len(chunks)}


@component
class FaissSearcher:
    def __init__(self, text_embedder: TextEmbedder) -> None:
        self.text_embedder = text_embedder

    @component.output_types(results=list[dict])
    def run(self, archive: bytes, query: str, top_k: int = 10) -> dict[str, list[dict]]:
        with TemporaryDirectory() as directory, ZipFile(BytesIO(archive)) as stored:
            index_path = Path(directory) / "index"
            index_path.with_suffix(".faiss").write_bytes(stored.read("index.faiss"))
            index_path.with_suffix(".json").write_bytes(stored.read("index.json"))
            document_store = FAISSDocumentStore(index_path=str(index_path))
            retriever = FAISSEmbeddingRetriever(
                document_store=document_store, top_k=top_k
            )
            documents = retriever.run(
                query_embedding=self.text_embedder.run(text=query)["embedding"],
                top_k=top_k,
            )["documents"]
        return {
            "results": [
                {
                    "content": document.content or "",
                    "meta": document.meta,
                    "score": document.score or 0.0,
                }
                for document in documents
            ]
        }
