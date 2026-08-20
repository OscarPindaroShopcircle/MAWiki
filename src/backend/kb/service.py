import mimetypes
import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.enums import UserRole
from ..files.models import FileModel, StorageType
from ..filesystem.base import FileSystem
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
    staged: list[tuple[FileModel, str]] = []
    try:
        if (
            not uploads
            or len(uploads) > MAX_UPLOAD_BATCH_FILES
            or sum(upload.size or 0 for upload in uploads) > MAX_UPLOAD_BATCH_BYTES
            or file_ids is not None
            and (len(file_ids) != len(uploads) or len(set(file_ids)) != len(file_ids))
        ):
            raise FileUploadException()

        ids = file_ids or [uuid.uuid4() for _ in uploads]
        linked_ids: set[uuid.UUID] = set()
        if file_ids is not None:
            existing_ids, linked_ids = await KnowledgeBaseRepository(
                db
            ).get_existing_file_ids(knowledge_base_id, file_ids)
            if existing_ids != linked_ids:
                raise FileUploadException()

        for upload, file_id in zip(uploads, ids, strict=True):
            if file_id in linked_ids:
                continue
            filename = Path(upload.filename or "").name
            if not filename or filename in {".", ".."} or len(filename) > 255:
                raise FileUploadException()

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
        return knowledge_base
    except Exception as exc:
        for _, location in staged:
            try:
                await filesystem.delete_async(location)
            except Exception:
                pass
        if isinstance(exc, FileUploadException):
            raise
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
