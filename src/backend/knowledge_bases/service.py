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
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ai.components.embedders import Model2VecDocumentEmbedder, Model2VecTextEmbedder
from ai.document_codec import MarkdownDocumentCodec, MarkdownDocumentFormatError
from ai.pipelines.rag import DocumentConverter, DocumentIndexer, HybridRetriever

from ..config import DatabaseSettingsProtocol
from ..db.db import DatabaseManager
from ..db.enums import UserRole
from ..files.models import FileModel, StorageType
from ..filesystem.base import FileSystem
from ..sources.exception import SourceAccessDeniedException
from ..sources.models import SourceModel, SourceOrigin
from ..sources.service import get_source
from ..tasks.models import TaskModel, TaskStatus
from ..tasks.repository import TaskRepository
from ..tasks.schemas import TaskCreate, TaskUpdate
from ..users.schemas import User
from .exception import (
    KnowledgeBaseNotConvertedException,
    KnowledgeBaseNotFoundException,
    KnowledgeBaseNotIndexedException,
    KnowledgeBaseOperationInProgressException,
    KnowledgeBaseOperationNotStartedException,
    KnowledgeBaseSourceFileNotFoundException,
)
from .models import KnowledgeBaseModel
from .repository import KnowledgeBaseRepository
from .schemas import (
    KnowledgeBaseCreate,
    KnowledgeBaseSearchRequest,
    KnowledgeBaseUpdate,
)

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


async def create_knowledge_base(
    db: AsyncSession, data: KnowledgeBaseCreate, user: User
) -> KnowledgeBaseModel:
    source = await get_source(db, data.source_id, user)
    if source.origin != SourceOrigin.USER or (
        not _is_admin(user) and source.created_by_id != user.id
    ):
        raise SourceAccessDeniedException(source.id)
    return await KnowledgeBaseRepository(db).create(data, user.id)


async def get_knowledge_base(
    db: AsyncSession,
    knowledge_base_id: uuid.UUID,
    user: User,
    include_source: bool = False,
    include_tasks: bool = False,
    include_index: bool = False,
) -> KnowledgeBaseModel:
    knowledge_base = await KnowledgeBaseRepository(db).get(
        knowledge_base_id,
        user.id,
        _is_admin(user),
        include_source,
        include_tasks,
        include_index,
    )
    if knowledge_base is None:
        raise KnowledgeBaseNotFoundException(knowledge_base_id)
    return knowledge_base


async def get_knowledge_bases(
    db: AsyncSession,
    user: User,
    page: int = 1,
    page_size: int = 20,
    include_source: bool = False,
) -> tuple[list[KnowledgeBaseModel], int]:
    return await KnowledgeBaseRepository(db).get_page(
        user.id, _is_admin(user), page, page_size, include_source
    )


async def update_knowledge_base(
    db: AsyncSession,
    knowledge_base_id: uuid.UUID,
    data: KnowledgeBaseUpdate,
    user: User,
) -> KnowledgeBaseModel:
    knowledge_base = await get_knowledge_base(db, knowledge_base_id, user)
    return await KnowledgeBaseRepository(db).update(knowledge_base, data)


async def delete_knowledge_base(
    db: AsyncSession,
    knowledge_base_id: uuid.UUID,
    user: User,
    filesystem: FileSystem | None = None,
) -> None:
    await get_knowledge_base(db, knowledge_base_id, user)
    knowledge_base = await _operation_knowledge_base(db, knowledge_base_id)
    converted_source = knowledge_base.converted_source
    files = list(converted_source.files) if converted_source is not None else []
    artifacts = files + (
        [knowledge_base.index_file] if knowledge_base.index_file else []
    )
    await KnowledgeBaseRepository(db).delete(knowledge_base)
    for file in artifacts:
        await db.delete(file)
    if converted_source is not None:
        await db.delete(converted_source)
    await db.flush()
    if filesystem is not None:
        for file in artifacts:
            with suppress(FileNotFoundError):
                await filesystem.delete_async(file.location)


async def _operation_knowledge_base(
    db: AsyncSession, knowledge_base_id: uuid.UUID, lock: bool = False
) -> KnowledgeBaseModel:
    knowledge_base = await KnowledgeBaseRepository(db).get_for_operation(
        knowledge_base_id, lock
    )
    if knowledge_base is None:
        raise KnowledgeBaseNotFoundException(knowledge_base_id)
    return knowledge_base


def _ensure_idle(knowledge_base: KnowledgeBaseModel) -> None:
    if any(
        task is not None and task.status in _RUNNING
        for task in (knowledge_base.conversion_task, knowledge_base.indexing_task)
    ):
        raise KnowledgeBaseOperationInProgressException()


async def start_knowledge_base_operation(
    db: AsyncSession, knowledge_base_id: uuid.UUID, user: User, operation: Operation
) -> TaskModel:
    await get_knowledge_base(db, knowledge_base_id, user)
    knowledge_base = await _operation_knowledge_base(db, knowledge_base_id, lock=True)
    _ensure_idle(knowledge_base)
    if operation == "indexing" and knowledge_base.converted_source_id is None:
        raise KnowledgeBaseNotConvertedException()
    task = await TaskRepository(db).create(
        TaskCreate(name=f"knowledge_base-{operation}-{knowledge_base.id}")
    )
    setattr(knowledge_base, f"{operation}_task", task)
    await db.flush()
    return task


async def poll_knowledge_base_operation(
    db: AsyncSession, knowledge_base_id: uuid.UUID, user: User, operation: Operation
) -> TaskModel:
    await get_knowledge_base(db, knowledge_base_id, user)
    knowledge_base = await _operation_knowledge_base(db, knowledge_base_id)
    task = getattr(knowledge_base, f"{operation}_task")
    if task is None:
        raise KnowledgeBaseOperationNotStartedException(operation)
    return task


def _converted_name(source_name: str, position: int, total: int) -> str:
    suffix = f".{position + 1}" if total > 1 else ""
    return f"{source_name[: 251 - len(suffix)]}{suffix}.md"


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


async def convert_knowledge_base_files(
    db: AsyncSession,
    knowledge_base_id: uuid.UUID,
    filesystem: FileSystem,
    converter: DocumentConverter | None = None,
) -> str:
    knowledge_base = await _operation_knowledge_base(db, knowledge_base_id)
    converter = converter or DocumentConverter()
    results = await asyncio.gather(
        *(
            _convert_file(file, filesystem, converter)
            for file in knowledge_base.source.files
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
        detail = ", ".join(unsupported + failed) or "source is empty"
        raise ValueError(f"No files could be converted: {detail}")

    converted_source = knowledge_base.converted_source
    if converted_source is None:
        converted_source = SourceModel(
            name=f"{knowledge_base.name} converted",
            origin=SourceOrigin.SYSTEM,
            created_by_id=knowledge_base.owner_id,
            files=[],
            shared_with=[],
        )
        db.add(converted_source)
        await db.flush()
        knowledge_base.converted_source = converted_source

    staged: list[FileModel] = []
    staged_locations: list[str] = []
    try:
        for source, documents in converted:
            for position, document in enumerate(documents):
                file_id = uuid.uuid4()
                location = f"sources/{converted_source.id}/{file_id}"
                staged_locations.append(location)
                document.meta.update(
                    source_file_id=str(source.id),
                    source_file_name=source.name,
                    output_index=position,
                )
                await filesystem.write_async(
                    location,
                    MarkdownDocumentCodec.dumps(
                        Document(
                            id=str(file_id),
                            content=document.content,
                            meta=document.meta,
                        )
                    ),
                )
                staged.append(
                    FileModel(
                        id=file_id,
                        name=_converted_name(source.name, position, len(documents)),
                        location=location,
                        mime_type="text/markdown",
                        storage_type=StorageType.LOCAL,
                    )
                )
    except OSError:
        await _remove_staged(filesystem, staged_locations)
        raise

    old_files = list(converted_source.files)
    old_index = knowledge_base.index_file
    try:
        converted_source.files = staged
        db.add_all(staged)
        knowledge_base.index_file = None
        knowledge_base.indexing_task = None
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


async def get_knowledge_base_file_conversion_data(
    db: AsyncSession,
    knowledge_base_id: uuid.UUID,
    user: User,
    filesystem: FileSystem,
) -> tuple[KnowledgeBaseModel, dict[str, list[tuple[FileModel, Document]]]]:
    await get_knowledge_base(db, knowledge_base_id, user)
    knowledge_base = await _operation_knowledge_base(db, knowledge_base_id)
    converted_by_source: dict[str, list[tuple[FileModel, Document]]] = {}
    converted_files = (
        knowledge_base.converted_source.files
        if knowledge_base.converted_source is not None
        else []
    )
    contents = await asyncio.gather(
        *(filesystem.read_async(file.location) for file in converted_files)
    )
    for file, content in zip(converted_files, contents, strict=True):
        try:
            document = MarkdownDocumentCodec.loads(content, document_id=str(file.id))
        except MarkdownDocumentFormatError as exc:
            logger.warning("Unable to read converted file %s: %s", file.id, exc)
            continue
        source_file_id = document.meta.get("source_file_id")
        if source_file_id:
            converted_by_source.setdefault(str(source_file_id), []).append(
                (file, document)
            )
    for converted_files_for_source in converted_by_source.values():
        converted_files_for_source.sort(
            key=lambda item: item[1].meta.get("output_index", 0)
        )
    return knowledge_base, converted_by_source


async def get_knowledge_base_file_chunks(
    db: AsyncSession,
    knowledge_base_id: uuid.UUID,
    source_file_id: uuid.UUID,
    user: User,
    filesystem: FileSystem,
) -> list[Document]:
    await get_knowledge_base(db, knowledge_base_id, user)
    knowledge_base = await _operation_knowledge_base(db, knowledge_base_id)
    if not any(file.id == source_file_id for file in knowledge_base.source.files):
        raise KnowledgeBaseSourceFileNotFoundException(source_file_id)
    if knowledge_base.index_file is None:
        return []
    archive = await filesystem.read_async(knowledge_base.index_file.location)
    document_store = await asyncio.to_thread(_restore_document_store, archive)
    chunks = document_store.filter_documents(
        {
            "field": "meta.source_file_id",
            "operator": "==",
            "value": str(source_file_id),
        }
    )
    return sorted(
        chunks,
        key=lambda chunk: (
            chunk.meta.get("output_index") or 0,
            chunk.meta.get("page_number") or 0,
            chunk.meta.get("split_idx_start") or 0,
            chunk.meta.get("split_id") or 0,
        ),
    )


async def index_knowledge_base_files(
    db: AsyncSession,
    knowledge_base_id: uuid.UUID,
    filesystem: FileSystem,
    document_embedder: DocumentEmbedder | None = None,
    embedding_dim: int | None = None,
) -> str:
    knowledge_base = await _operation_knowledge_base(db, knowledge_base_id)
    if knowledge_base.converted_source is None:
        raise KnowledgeBaseNotConvertedException()
    files = knowledge_base.converted_source.files
    if not files:
        raise ValueError("The converted source is empty")
    contents = await asyncio.gather(
        *(filesystem.read_async(file.location) for file in files)
    )
    documents = []
    for file, content in zip(files, contents, strict=True):
        document = MarkdownDocumentCodec.loads(content, document_id=str(file.id))
        document.meta.update(file_id=str(file.id), file_name=file.name)
        documents.append(document)
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
    location = f"knowledge-bases/{knowledge_base.id}/indexes/{file_id}.zip"
    try:
        await filesystem.write_async(location, archive)
        index_file = FileModel(
            id=file_id,
            name=f"{knowledge_base.name}.faiss.zip",
            location=location,
            mime_type="application/zip",
            storage_type=StorageType.LOCAL,
        )
        old_index = knowledge_base.index_file
        db.add(index_file)
        knowledge_base.index_file = index_file
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


async def search_knowledge_base(
    db: AsyncSession,
    knowledge_base_id: uuid.UUID,
    data: KnowledgeBaseSearchRequest,
    filesystem: FileSystem,
    text_embedder: TextEmbedder | None = None,
) -> list[dict]:
    knowledge_base = await _operation_knowledge_base(db, knowledge_base_id)
    if knowledge_base.index_file is None:
        raise KnowledgeBaseNotIndexedException()
    archive = await filesystem.read_async(knowledge_base.index_file.location)
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
            "source_file_id": document.meta["source_file_id"],
            "source_file_name": document.meta["source_file_name"],
        }
        for document in result["documents"]
    ]


async def get_mcp_knowledge_bases(db: AsyncSession) -> list[KnowledgeBaseModel]:
    result = await db.execute(
        select(KnowledgeBaseModel)
        .where(KnowledgeBaseModel.index_file_id.is_not(None))
        .order_by(KnowledgeBaseModel.name, KnowledgeBaseModel.id)
    )
    return list(result.scalars().all())


async def get_mcp_knowledge_base_file_content(
    db: AsyncSession,
    knowledge_base_id: uuid.UUID,
    source_file_id: uuid.UUID,
    filesystem: FileSystem,
) -> tuple[str, str]:
    knowledge_base = await _operation_knowledge_base(db, knowledge_base_id)
    source_file = next(
        (file for file in knowledge_base.source.files if file.id == source_file_id),
        None,
    )
    if source_file is None:
        raise KnowledgeBaseSourceFileNotFoundException(source_file_id)
    converted_files = (
        knowledge_base.converted_source.files if knowledge_base.converted_source else []
    )
    contents = await asyncio.gather(
        *(filesystem.read_async(file.location) for file in converted_files)
    )
    documents: list[Document] = []
    for file, content in zip(converted_files, contents, strict=True):
        try:
            document = MarkdownDocumentCodec.loads(content, document_id=str(file.id))
        except MarkdownDocumentFormatError as exc:
            logger.warning("Unable to read converted file %s: %s", file.id, exc)
            continue
        if document.meta.get("source_file_id") == str(source_file_id):
            documents.append(document)
    documents.sort(key=lambda document: document.meta.get("output_index", 0))
    return source_file.name, "\n\n".join(
        document.content or "" for document in documents
    )


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
    knowledge_base_id: uuid.UUID,
    operation: Operation,
) -> None:
    manager = DatabaseManager(database)
    try:
        async with manager.async_session() as db:
            await _set_task(db, task_id, TaskStatus.IN_PROGRESS, 0)
        try:
            async with manager.async_session() as db:
                if operation == "conversion":
                    message = await convert_knowledge_base_files(
                        db, knowledge_base_id, filesystem
                    )
                else:
                    message = await index_knowledge_base_files(
                        db, knowledge_base_id, filesystem
                    )
                await _set_task(db, task_id, TaskStatus.SUCCESS, 100, message)
        except Exception as exc:
            logger.exception(
                "knowledge base %s failed for %s", operation, knowledge_base_id
            )
            async with manager.async_session() as db:
                await _set_task(db, task_id, TaskStatus.FAILED, 100, str(exc)[:1024])
    finally:
        await manager.close()


async def run_conversion_job(
    database: DatabaseSettingsProtocol,
    filesystem: FileSystem,
    task_id: uuid.UUID,
    knowledge_base_id: uuid.UUID,
) -> None:
    await _run_operation_job(
        database, filesystem, task_id, knowledge_base_id, "conversion"
    )


async def run_indexing_job(
    database: DatabaseSettingsProtocol,
    filesystem: FileSystem,
    task_id: uuid.UUID,
    knowledge_base_id: uuid.UUID,
) -> None:
    await _run_operation_job(
        database, filesystem, task_id, knowledge_base_id, "indexing"
    )
