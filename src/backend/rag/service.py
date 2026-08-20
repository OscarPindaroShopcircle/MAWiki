import asyncio
import logging
import uuid
from contextlib import suppress
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from docx.opc.exceptions import PackageNotFoundError
from haystack import Document
from haystack.components.embedders.types import DocumentEmbedder, TextEmbedder
from haystack.dataclasses import ByteStream
from haystack_integrations.components.retrievers.faiss import FAISSEmbeddingRetriever
from haystack_integrations.document_stores.faiss import FAISSDocumentStore
from openpyxl.utils.exceptions import InvalidFileException
from pypdf.errors import PdfReadError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ai.components.embedders import Model2VecDocumentEmbedder, Model2VecTextEmbedder
from ai.pipelines.rag import DocumentConverter, DocumentIndexer, HybridRetriever

from ..config import DatabaseSettingsProtocol
from ..db.db import DatabaseManager
from ..db.enums import UserRole
from ..files.models import FileModel, StorageType
from ..filesystem.base import FileSystem
from ..kb.exception import KnowledgeBaseAccessDeniedException
from ..kb.models import KnowledgeBaseModel
from ..kb.service import get_knowledge_base
from ..tasks.models import TaskModel, TaskStatus
from ..tasks.repository import TaskRepository
from ..tasks.schemas import TaskCreate, TaskUpdate
from ..users.schemas import User
from .exception import (
    RagNotConvertedException,
    RagNotFoundException,
    RagNotIndexedException,
    RagOperationInProgressException,
    RagOperationNotStartedException,
)
from .models import RagModel
from .repository import RagRepository
from .schemas import RagCreate, RagSearchRequest, RagUpdate

Operation = Literal["conversion", "indexing"]
_RUNNING = {TaskStatus.WAITING, TaskStatus.IN_PROGRESS}
_CONVERSION_ERRORS = (
    BadZipFile,
    EOFError,
    InvalidFileException,
    OSError,
    PackageNotFoundError,
    PdfReadError,
    UnicodeError,
    ValueError,
)
logger = logging.getLogger(__name__)


def _is_admin(user: User) -> bool:
    return user.role == UserRole.ADMIN


async def create_rag_model(db: AsyncSession, data: RagCreate, user: User) -> RagModel:
    knowledge_base = await get_knowledge_base(db, data.source_knowledge_base_id, user)
    if not _is_admin(user) and knowledge_base.created_by_id != user.id:
        raise KnowledgeBaseAccessDeniedException(knowledge_base.id)
    return await RagRepository(db).create(data, user.id)


async def get_rag_model(
    db: AsyncSession,
    rag_id: uuid.UUID,
    user: User,
    include_source: bool = False,
    include_tasks: bool = False,
    include_index: bool = False,
) -> RagModel:
    rag = await RagRepository(db).get(
        rag_id,
        user.id,
        _is_admin(user),
        include_source,
        include_tasks,
        include_index,
    )
    if rag is None:
        raise RagNotFoundException(rag_id)
    return rag


async def get_rag_models(
    db: AsyncSession,
    user: User,
    page: int = 1,
    page_size: int = 20,
    include_source: bool = False,
) -> tuple[list[RagModel], int]:
    return await RagRepository(db).get_page(
        user.id, _is_admin(user), page, page_size, include_source
    )


async def update_rag_model(
    db: AsyncSession, rag_id: uuid.UUID, data: RagUpdate, user: User
) -> RagModel:
    rag = await get_rag_model(db, rag_id, user)
    return await RagRepository(db).update(rag, data)


async def delete_rag_model(
    db: AsyncSession,
    rag_id: uuid.UUID,
    user: User,
    filesystem: FileSystem | None = None,
) -> None:
    rag = await get_rag_model(db, rag_id, user, include_index=True)
    index_file = rag.index_file
    await RagRepository(db).delete(rag)
    if index_file is not None:
        await db.delete(index_file)
        await db.flush()
        if filesystem is not None:
            await filesystem.delete_async(index_file.location)


async def _operation_rag(
    db: AsyncSession, rag_id: uuid.UUID, lock: bool = False
) -> RagModel:
    rag = await RagRepository(db).get_for_operation(rag_id, lock)
    if rag is None:
        raise RagNotFoundException(rag_id)
    return rag


def _ensure_idle(rag: RagModel) -> None:
    if any(
        task is not None and task.status in _RUNNING
        for task in (rag.conversion_task, rag.indexing_task)
    ):
        raise RagOperationInProgressException()


async def start_rag_operation(
    db: AsyncSession, rag_id: uuid.UUID, user: User, operation: Operation
) -> TaskModel:
    await get_rag_model(db, rag_id, user)
    rag = await _operation_rag(db, rag_id, lock=True)
    _ensure_idle(rag)
    if operation == "indexing" and rag.converted_knowledge_base_id is None:
        raise RagNotConvertedException()
    task = await TaskRepository(db).create(TaskCreate(name=f"rag-{operation}-{rag.id}"))
    setattr(rag, f"{operation}_task", task)
    await db.flush()
    return task


async def poll_rag_operation(
    db: AsyncSession, rag_id: uuid.UUID, user: User, operation: Operation
) -> TaskModel:
    await get_rag_model(db, rag_id, user)
    rag = await _operation_rag(db, rag_id)
    task = getattr(rag, f"{operation}_task")
    if task is None:
        raise RagOperationNotStartedException(operation)
    return task


def _converted_name(source_name: str, position: int, total: int) -> str:
    suffix = f".{position + 1}" if total > 1 else ""
    return f"{source_name[: 250 - len(suffix)]}{suffix}.txt"


async def _remove_staged(filesystem: FileSystem, locations: list[str]) -> None:
    for location in locations:
        try:
            await filesystem.delete_async(location)
        except OSError as cleanup_error:
            logger.warning(
                "Unable to remove staged file %s: %s", location, cleanup_error
            )


def _archive_document_store(document_store: FAISSDocumentStore) -> bytes:
    with TemporaryDirectory() as directory:
        index_path = Path(directory) / "index"
        document_store.save(index_path)
        output = BytesIO()
        with ZipFile(output, "w", ZIP_DEFLATED) as archive:
            archive.write(index_path.with_suffix(".faiss"), "index.faiss")
            archive.write(index_path.with_suffix(".json"), "index.json")
    return output.getvalue()


def _restore_document_store(archive: bytes) -> FAISSDocumentStore:
    with TemporaryDirectory() as directory, ZipFile(BytesIO(archive)) as stored:
        index_path = Path(directory) / "index"
        index_path.with_suffix(".faiss").write_bytes(stored.read("index.faiss"))
        index_path.with_suffix(".json").write_bytes(stored.read("index.json"))
        return FAISSDocumentStore(index_path=str(index_path))


async def _convert_file(
    file: FileModel, filesystem: FileSystem, converter: DocumentConverter
) -> tuple[FileModel, list[Document] | None, str | None]:
    try:
        content = await filesystem.read_async(file.location)
        documents = await converter.run_async(
            sources=[
                ByteStream(
                    content,
                    meta={"file_name": file.name, "source_file_id": str(file.id)},
                    mime_type=file.mime_type,
                )
            ]
        )
        converted = [
            doc for doc in documents["documents"] if (doc.content or "").strip()
        ]
        return (file, converted, None) if converted else (file, None, "unsupported")
    except KeyError as exc:
        if exc.args != ("documents",):
            raise
        return file, None, "unsupported"
    except _CONVERSION_ERRORS as exc:
        return file, None, str(exc)


async def convert_rag_model_files(
    db: AsyncSession,
    rag_id: uuid.UUID,
    filesystem: FileSystem,
    converter: DocumentConverter | None = None,
) -> str:
    rag = await _operation_rag(db, rag_id)
    converter = converter or DocumentConverter()
    results = await asyncio.gather(
        *(
            _convert_file(file, filesystem, converter)
            for file in rag.source_knowledge_base.files
        )
    )
    converted = [(file, documents) for file, documents, _ in results if documents]
    unsupported = [file.name for file, _, error in results if error == "unsupported"]
    failed = [
        f"{file.name} ({error})"
        for file, _, error in results
        if error not in {None, "unsupported"}
    ]
    if not converted:
        detail = ", ".join(unsupported + failed) or "source knowledge base is empty"
        raise ValueError(f"No files could be converted: {detail}")

    knowledge_base = rag.converted_knowledge_base
    if knowledge_base is None:
        knowledge_base = KnowledgeBaseModel(
            name=f"{rag.name} converted",
            created_by_id=rag.owner_id,
            files=[],
            shared_with=[],
        )
        db.add(knowledge_base)
        await db.flush()
        rag.converted_knowledge_base = knowledge_base

    staged: list[FileModel] = []
    staged_locations: list[str] = []
    try:
        for source, documents in converted:
            for position, document in enumerate(documents):
                file_id = uuid.uuid4()
                location = f"knowledge-bases/{knowledge_base.id}/{file_id}"
                staged_locations.append(location)
                await filesystem.write_async(
                    location, (document.content or "").encode("utf-8")
                )
                staged.append(
                    FileModel(
                        id=file_id,
                        name=_converted_name(source.name, position, len(documents)),
                        location=location,
                        mime_type="text/plain",
                        storage_type=StorageType.LOCAL,
                    )
                )
    except OSError:
        await _remove_staged(filesystem, staged_locations)
        raise

    old_files = list(knowledge_base.files)
    old_index = rag.index_file
    try:
        knowledge_base.files = staged
        db.add_all(staged)
        rag.index_file = None
        rag.indexing_task = None
        for file in old_files:
            await db.delete(file)
        if old_index is not None:
            await db.delete(old_index)
        await db.flush()
    except SQLAlchemyError:
        await _remove_staged(filesystem, staged_locations)
        raise
    for file in old_files + ([old_index] if old_index is not None else []):
        with suppress(FileNotFoundError):
            await filesystem.delete_async(file.location)

    message = f"Converted {len(converted)}/{len(results)} source files"
    if unsupported:
        message += f"; unsupported: {', '.join(unsupported)}"
    if failed:
        message += f"; failed: {', '.join(failed)}"
    return message[:1024]


async def index_rag_model_files(
    db: AsyncSession,
    rag_id: uuid.UUID,
    filesystem: FileSystem,
    document_embedder: DocumentEmbedder | None = None,
    embedding_dim: int | None = None,
) -> str:
    rag = await _operation_rag(db, rag_id)
    if rag.converted_knowledge_base is None:
        raise RagNotConvertedException()
    files = rag.converted_knowledge_base.files
    if not files:
        raise ValueError("The converted knowledge base is empty")
    contents = await asyncio.gather(
        *(filesystem.read_async(file.location) for file in files)
    )
    documents = [
        Document(
            content=content.decode("utf-8"),
            meta={"file_id": str(file.id), "file_name": file.name},
        )
        for file, content in zip(files, contents, strict=True)
    ]
    if document_embedder is None:
        model2vec_embedder = Model2VecDocumentEmbedder()
        await asyncio.to_thread(model2vec_embedder.warm_up)
        document_embedder = model2vec_embedder
        embedding_dim = model2vec_embedder.model.dim
    if embedding_dim is None:
        raise ValueError("embedding_dim is required for a custom document embedder")
    document_store = FAISSDocumentStore(embedding_dim=embedding_dim)
    indexer = DocumentIndexer(document_store, document_embedder)
    result = await asyncio.to_thread(indexer.run, documents=documents)
    archive = await asyncio.to_thread(_archive_document_store, document_store)
    file_id = uuid.uuid4()
    location = f"rag-models/{rag.id}/indexes/{file_id}.zip"
    try:
        await filesystem.write_async(location, archive)
        index_file = FileModel(
            id=file_id,
            name=f"{rag.name}.faiss.zip",
            location=location,
            mime_type="application/zip",
            storage_type=StorageType.LOCAL,
        )
        old_index = rag.index_file
        db.add(index_file)
        rag.index_file = index_file
        if old_index is not None:
            await db.delete(old_index)
        await db.flush()
    except OSError, SQLAlchemyError:
        await _remove_staged(filesystem, [location])
        raise
    if old_index is not None:
        with suppress(FileNotFoundError):
            await filesystem.delete_async(old_index.location)
    return f"Indexed {result['documents_written']} document chunks"


async def search_rag_model(
    db: AsyncSession,
    rag_id: uuid.UUID,
    data: RagSearchRequest,
    user: User,
    filesystem: FileSystem,
    text_embedder: TextEmbedder | None = None,
) -> list[dict]:
    await get_rag_model(db, rag_id, user)
    rag = await _operation_rag(db, rag_id)
    if rag.index_file is None:
        raise RagNotIndexedException()
    archive = await filesystem.read_async(rag.index_file.location)
    document_store = await asyncio.to_thread(_restore_document_store, archive)
    retriever = HybridRetriever(
        text_embedder or Model2VecTextEmbedder(),
        FAISSEmbeddingRetriever(document_store=document_store, top_k=data.top_k),
    )
    result = await retriever.run_async(query=data.query)
    return [
        {
            "content": document.content or "",
            "score": document.score or 0.0,
            "file_id": document.meta["file_id"],
            "file_name": document.meta["file_name"],
        }
        for document in result["documents"]
    ]


async def _set_task(
    db: AsyncSession,
    task_id: uuid.UUID,
    status: TaskStatus,
    completion: float,
    message: str | None = None,
) -> None:
    await TaskRepository(db).update(
        task_id,
        TaskUpdate(status=status, completion=completion, message=message),
    )


async def _run_operation_job(
    database: DatabaseSettingsProtocol,
    filesystem: FileSystem,
    task_id: uuid.UUID,
    rag_id: uuid.UUID,
    operation: Operation,
) -> None:
    manager = DatabaseManager(database)
    try:
        async with manager.async_session() as db:
            await _set_task(db, task_id, TaskStatus.IN_PROGRESS, 0)
        try:
            async with manager.async_session() as db:
                if operation == "conversion":
                    message = await convert_rag_model_files(db, rag_id, filesystem)
                else:
                    message = await index_rag_model_files(db, rag_id, filesystem)
                await _set_task(db, task_id, TaskStatus.SUCCESS, 100, message)
        except Exception as exc:
            logger.exception("RAG %s failed for %s", operation, rag_id)
            async with manager.async_session() as db:
                await _set_task(db, task_id, TaskStatus.FAILED, 100, str(exc)[:1024])
    finally:
        await manager.close()


async def run_conversion_job(
    database: DatabaseSettingsProtocol,
    filesystem: FileSystem,
    task_id: uuid.UUID,
    rag_id: uuid.UUID,
) -> None:
    await _run_operation_job(database, filesystem, task_id, rag_id, "conversion")


async def run_indexing_job(
    database: DatabaseSettingsProtocol,
    filesystem: FileSystem,
    task_id: uuid.UUID,
    rag_id: uuid.UUID,
) -> None:
    await _run_operation_job(database, filesystem, task_id, rag_id, "indexing")
