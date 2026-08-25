import mimetypes
import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.enums import UserRole
from ..files.models import FileModel, StorageType
from ..filesystem.base import FileSystem
from ..log import get_logger
from ..users.schemas import User
from .constants import MAX_UPLOAD_BATCH_BYTES, MAX_UPLOAD_BATCH_FILES
from .exception import (
    FileUploadException,
    KnowledgeBaseAccessDeniedException,
    KnowledgeBaseFileNotFoundException,
    KnowledgeBaseNotFoundException,
    SharedUserNotFoundException,
)
from .models import KnowledgeBaseModel
from .repository import KnowledgeBaseRepository
from .schemas import KnowledgeBaseCreate, KnowledgeBaseUpdate

logger = get_logger(__name__)


def _is_admin(user: User) -> bool:
    return user.role == UserRole.ADMIN


async def create_knowledge_base(
    db: AsyncSession,
    data: KnowledgeBaseCreate,
    user: User,
) -> KnowledgeBaseModel:
    try:
        return await KnowledgeBaseRepository(db).create(data, user.id)
    except ValueError as exc:
        raise SharedUserNotFoundException() from exc


async def get_knowledge_base(
    db: AsyncSession,
    knowledge_base_id: uuid.UUID,
    user: User,
    include_files: bool = False,
    include_shared_with: bool = False,
) -> KnowledgeBaseModel:
    knowledge_base = await KnowledgeBaseRepository(db).get(
        knowledge_base_id,
        user.id,
        _is_admin(user),
        include_files,
        include_shared_with,
    )
    if knowledge_base is None:
        raise KnowledgeBaseNotFoundException(knowledge_base_id)
    return knowledge_base


async def get_knowledge_bases(
    db: AsyncSession,
    user: User,
    page: int = 1,
    page_size: int = 20,
    include_files: bool = False,
    include_shared_with: bool = False,
) -> tuple[list[KnowledgeBaseModel], int]:
    return await KnowledgeBaseRepository(db).get_page(
        user.id,
        _is_admin(user),
        page,
        page_size,
        include_files,
        include_shared_with,
    )


async def get_knowledge_base_files(
    db: AsyncSession,
    knowledge_base_id: uuid.UUID,
    user: User,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[FileModel], bool]:
    await get_knowledge_base(db, knowledge_base_id, user)
    return await KnowledgeBaseRepository(db).get_files_page(
        knowledge_base_id, page, page_size
    )


async def update_knowledge_base(
    db: AsyncSession,
    knowledge_base_id: uuid.UUID,
    data: KnowledgeBaseUpdate,
    user: User,
    include_files: bool = False,
    include_shared_with: bool = False,
) -> KnowledgeBaseModel:
    repository = KnowledgeBaseRepository(db)
    knowledge_base = await get_knowledge_base(
        db,
        knowledge_base_id,
        user,
        include_files,
        include_shared_with,
    )
    if not _is_admin(user) and knowledge_base.created_by_id != user.id:
        raise KnowledgeBaseAccessDeniedException(knowledge_base_id)

    try:
        return await repository.update(knowledge_base, data)
    except ValueError as exc:
        raise SharedUserNotFoundException() from exc


async def upload_files_to_knowledge_base(
    db: AsyncSession,
    knowledge_base_id: uuid.UUID,
    uploads: list[UploadFile],
    user: User,
    filesystem: FileSystem,
    include_existing_files: bool = True,
    file_ids: list[uuid.UUID] | None = None,
) -> KnowledgeBaseModel:
    knowledge_base = await get_knowledge_base(
        db, knowledge_base_id, user, include_files=include_existing_files
    )
    if not _is_admin(user) and knowledge_base.created_by_id != user.id:
        raise KnowledgeBaseAccessDeniedException(knowledge_base_id)
    logger.info(
        "Upload started",
        kb_id=str(knowledge_base_id),
        user_id=str(user.id),
        file_count=len(uploads),
        total_bytes=sum(u.size or 0 for u in uploads),
    )
    staged: list[tuple[FileModel, str]] = []
    try:
        total_bytes = sum(upload.size or 0 for upload in uploads)
        if not uploads:
            raise FileUploadException("No files provided")
        if len(uploads) > MAX_UPLOAD_BATCH_FILES:
            raise FileUploadException(
                f"Too many files: {len(uploads)} (max {MAX_UPLOAD_BATCH_FILES})"
            )
        if total_bytes > MAX_UPLOAD_BATCH_BYTES:
            raise FileUploadException(
                f"Upload too large: {total_bytes} bytes (max {MAX_UPLOAD_BATCH_BYTES})"
            )
        if file_ids is not None and (
            len(file_ids) != len(uploads) or len(set(file_ids)) != len(file_ids)
        ):
            raise FileUploadException("file_ids count mismatch or duplicate ids")

        ids = file_ids or [uuid.uuid4() for _ in uploads]
        linked_ids: set[uuid.UUID] = set()
        if file_ids is not None:
            existing_ids, linked_ids = await KnowledgeBaseRepository(
                db
            ).get_existing_file_ids(knowledge_base_id, file_ids)
            if existing_ids != linked_ids:
                raise FileUploadException(
                    "Some file_ids do not belong to this knowledge base"
                )

        for upload, file_id in zip(uploads, ids, strict=True):
            if file_id in linked_ids:
                continue
            filename = Path(upload.filename or "").name
            if not filename or filename in {".", ".."}:
                raise FileUploadException(f"Invalid filename: {filename!r}")
            if len(filename) > 255:
                raise FileUploadException(f"Filename too long: {len(filename)} chars")

            location = f"knowledge-bases/{knowledge_base.id}/{file_id}"
            await upload.seek(0)
            await filesystem.write_async(location, upload.file)
            staged.append(
                (
                    FileModel(
                        id=file_id,
                        name=filename,
                        location=location,
                        mime_type=upload.content_type
                        or mimetypes.guess_type(filename)[0],
                        storage_type=StorageType.LOCAL,
                    ),
                    location,
                )
            )

        for file, _ in staged:
            db.add(file)
            knowledge_base.files.append(file)
        await db.flush()
        logger.info(
            "Upload complete",
            kb_id=str(knowledge_base_id),
            file_count=len(staged),
            total_bytes=total_bytes,
        )
        return knowledge_base
    except Exception as exc:
        for _, location in staged:
            try:
                await filesystem.delete_async(location)
            except Exception:
                pass
        if isinstance(exc, FileUploadException):
            logger.error(
                "Upload rejected", kb_id=str(knowledge_base_id), reason=exc.detail
            )
            raise
        logger.error(
            "Upload failed",
            kb_id=str(knowledge_base_id),
            error=str(exc),
        )
        raise FileUploadException() from exc
    finally:
        for upload in uploads:
            await upload.close()


async def read_knowledge_base_file(
    db: AsyncSession,
    knowledge_base_id: uuid.UUID,
    file_id: uuid.UUID,
    user: User,
    filesystem: FileSystem,
) -> tuple[FileModel, bytes]:
    knowledge_base = await get_knowledge_base(
        db, knowledge_base_id, user, include_files=True
    )
    file = next((file for file in knowledge_base.files if file.id == file_id), None)
    if file is None:
        raise KnowledgeBaseFileNotFoundException(file_id)
    return file, await filesystem.read_async(file.location)


async def delete_knowledge_base(
    db: AsyncSession,
    knowledge_base_id: uuid.UUID,
    user: User,
) -> None:
    repository = KnowledgeBaseRepository(db)
    knowledge_base = await get_knowledge_base(db, knowledge_base_id, user)
    if not _is_admin(user) and knowledge_base.created_by_id != user.id:
        raise KnowledgeBaseAccessDeniedException(knowledge_base_id)
    await repository.delete(knowledge_base)
