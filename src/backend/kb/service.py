import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import AppConfig
from ..db.enums import UserRole
from ..files.models import FileModel, StorageType
from ..filesystem import LocalFileSystem
from ..users.schemas import User
from .exception import (
    FileUploadException,
    KnowledgeBaseAccessDeniedException,
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
    config: AppConfig,
) -> KnowledgeBaseModel:
    knowledge_base = await get_knowledge_base(
        db, knowledge_base_id, user, include_files=True
    )
    if not _is_admin(user) and knowledge_base.created_by_id != user.id:
        raise KnowledgeBaseAccessDeniedException(knowledge_base_id)
    if not uploads:
        raise FileUploadException()

    filesystem = LocalFileSystem(config.storage.storage_root)
    staged: list[tuple[FileModel, str]] = []
    try:
        for upload in uploads:
            filename = Path(upload.filename or "").name
            if not filename or filename in {".", ".."} or len(filename) > 255:
                raise FileUploadException()

            file_id = uuid.uuid4()
            location = f"knowledge-bases/{knowledge_base.id}/{file_id}"
            await upload.seek(0)
            await filesystem.write_async(location, upload.file)
            staged.append(
                (
                    FileModel(
                        id=file_id,
                        name=filename,
                        location=location,
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
