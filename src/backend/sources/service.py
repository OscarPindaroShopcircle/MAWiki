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
    SharedUserNotFoundException,
    SourceAccessDeniedException,
    SourceFileNotFoundException,
    SourceNotFoundException,
    SystemSourceMutationException,
)
from .models import SourceModel, SourceOrigin
from .repository import SourceRepository
from .schemas import SourceCreate, SourceUpdate

logger = get_logger(__name__)


def _is_admin(user: User) -> bool:
    return user.role == UserRole.ADMIN


def _ensure_mutable(source: SourceModel) -> None:
    if source.origin == SourceOrigin.SYSTEM:
        raise SystemSourceMutationException()


async def create_source(
    db: AsyncSession, data: SourceCreate, user: User
) -> SourceModel:
    try:
        return await SourceRepository(db).create(data, user.id)
    except ValueError as exc:
        raise SharedUserNotFoundException() from exc


async def get_source(
    db: AsyncSession,
    source_id: uuid.UUID,
    user: User,
    include_files: bool = False,
    include_shared_with: bool = False,
) -> SourceModel:
    source = await SourceRepository(db).get(
        source_id, user.id, _is_admin(user), include_files, include_shared_with
    )
    if source is None:
        raise SourceNotFoundException(source_id)
    return source


async def get_sources(
    db: AsyncSession,
    user: User,
    page: int = 1,
    page_size: int = 20,
    include_files: bool = False,
    include_shared_with: bool = False,
    origin: SourceOrigin = SourceOrigin.USER,
) -> tuple[list[SourceModel], int]:
    return await SourceRepository(db).get_page(
        user.id,
        _is_admin(user),
        page,
        page_size,
        include_files,
        include_shared_with,
        origin,
    )


async def get_source_files(
    db: AsyncSession,
    source_id: uuid.UUID,
    user: User,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[FileModel], bool]:
    await get_source(db, source_id, user)
    return await SourceRepository(db).get_files_page(source_id, page, page_size)


async def update_source(
    db: AsyncSession,
    source_id: uuid.UUID,
    data: SourceUpdate,
    user: User,
    include_files: bool = False,
    include_shared_with: bool = False,
) -> SourceModel:
    source = await get_source(db, source_id, user, include_files, include_shared_with)
    _ensure_mutable(source)
    if not _is_admin(user) and source.created_by_id != user.id:
        raise SourceAccessDeniedException(source_id)
    try:
        return await SourceRepository(db).update(source, data)
    except ValueError as exc:
        raise SharedUserNotFoundException() from exc


async def upload_files_to_source(
    db: AsyncSession,
    source_id: uuid.UUID,
    uploads: list[UploadFile],
    user: User,
    filesystem: FileSystem,
    include_existing_files: bool = True,
    file_ids: list[uuid.UUID] | None = None,
) -> SourceModel:
    source = await get_source(db, source_id, user, include_files=include_existing_files)
    _ensure_mutable(source)
    if not _is_admin(user) and source.created_by_id != user.id:
        raise SourceAccessDeniedException(source_id)
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
            existing_ids, linked_ids = await SourceRepository(db).get_existing_file_ids(
                source_id, file_ids
            )
            if existing_ids != linked_ids:
                raise FileUploadException("Some file_ids do not belong to this source")
        for upload, file_id in zip(uploads, ids, strict=True):
            if file_id in linked_ids:
                continue
            filename = Path(upload.filename or "").name
            if not filename or filename in {".", ".."}:
                raise FileUploadException(f"Invalid filename: {filename!r}")
            if len(filename) > 255:
                raise FileUploadException(f"Filename too long: {len(filename)} chars")
            location = f"sources/{source.id}/{file_id}"
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
            source.files.append(file)
        await db.flush()
        return source
    except Exception as exc:
        for _, location in staged:
            try:
                await filesystem.delete_async(location)
            except Exception:
                pass
        if isinstance(exc, FileUploadException):
            raise
        logger.error("Source upload failed", source_id=str(source_id), error=str(exc))
        raise FileUploadException() from exc
    finally:
        for upload in uploads:
            await upload.close()


async def read_source_file(
    db: AsyncSession,
    source_id: uuid.UUID,
    file_id: uuid.UUID,
    user: User,
    filesystem: FileSystem,
) -> tuple[FileModel, bytes]:
    source = await get_source(db, source_id, user, include_files=True)
    file = next((file for file in source.files if file.id == file_id), None)
    if file is None:
        raise SourceFileNotFoundException(file_id)
    return file, await filesystem.read_async(file.location)


async def delete_source(db: AsyncSession, source_id: uuid.UUID, user: User) -> None:
    source = await get_source(db, source_id, user)
    _ensure_mutable(source)
    if not _is_admin(user) and source.created_by_id != user.id:
        raise SourceAccessDeniedException(source_id)
    await SourceRepository(db).delete(source)
