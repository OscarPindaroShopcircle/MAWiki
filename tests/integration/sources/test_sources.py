import io
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import Headers

from src.backend.filesystem import LocalFileSystem
from src.backend.db.enums import UserRole
from src.backend.sources.constants import MAX_UPLOAD_BATCH_BYTES
from src.backend.sources.exception import (
    FileUploadException,
    SourceAccessDeniedException,
    SourceFileNotFoundException,
    SourceNotFoundException,
    SystemSourceMutationException,
)
from src.backend.sources.routes import download_source_file
from src.backend.sources.models import SourceModel, SourceOrigin
from src.backend.sources.schemas import SourceCreate, SourceUpdate
from src.backend.sources.views import upload_source_files_view
from src.backend.sources.service import (
    create_source,
    delete_source,
    get_source,
    get_source_files,
    get_sources,
    read_source_file,
    update_source,
    upload_files_to_source,
)
from src.backend.users.models import UserModel
from src.backend.users.schemas import User


@pytest_asyncio.fixture
async def users(db_session: AsyncSession) -> list[User]:
    creator = UserModel(
        name="Creator",
        email="creator@example.com",
        role=UserRole.MEMBER,
    )
    viewer = UserModel(
        name="Viewer",
        email="viewer@example.com",
        role=UserRole.MEMBER,
    )
    stranger = UserModel(
        name="Stranger",
        email="stranger@example.com",
        role=UserRole.MEMBER,
    )
    admin = UserModel(
        name="Admin",
        email="admin@example.com",
        role=UserRole.ADMIN,
    )
    for user in [creator, viewer, stranger, admin]:
        db_session.add(user)
        await db_session.flush()
        await db_session.refresh(user)
    return [User.model_validate(user) for user in [creator, viewer, stranger, admin]]


@pytest.mark.integration
async def test_source_visibility_and_mutation_authorization(
    db_session: AsyncSession, users: list[User]
):
    creator, viewer, stranger, admin = users
    source = await create_source(
        db_session,
        SourceCreate(name="Shared source", shared_with=[viewer.id]),
        creator,
    )

    assert (await get_source(db_session, source.id, creator)).name == "Shared source"
    assert (await get_source(db_session, source.id, viewer)).name == "Shared source"
    with pytest.raises(SourceNotFoundException):
        await get_source(db_session, source.id, stranger)

    with pytest.raises(SourceAccessDeniedException):
        await update_source(
            db_session,
            source.id,
            SourceUpdate(name="Not allowed"),
            viewer,
        )

    updated = await update_source(
        db_session,
        source.id,
        SourceUpdate(name="Updated source"),
        creator,
    )
    assert updated.name == "Updated source"

    admin_updated = await update_source(
        db_session,
        source.id,
        SourceUpdate(name="Admin Updated source"),
        admin,
    )
    assert admin_updated.name == "Admin Updated source"

    with pytest.raises(SourceAccessDeniedException):
        await delete_source(db_session, source.id, viewer)


@pytest.mark.integration
async def test_upload_files_persists_metadata_and_association(
    db_session: AsyncSession, users: list[User], tmp_path: Path
):
    creator = users[0]
    source = await create_source(
        db_session,
        SourceCreate(name="Uploads"),
        creator,
    )
    uploads = [
        UploadFile(file=io.BytesIO(b"first"), filename="first.txt"),
        UploadFile(
            file=io.BytesIO(b"second"),
            filename="second.pdf",
            headers=Headers({"content-type": "application/pdf"}),
        ),
    ]

    updated = await upload_files_to_source(
        db_session,
        source.id,
        uploads,
        creator,
        LocalFileSystem(tmp_path),
    )

    assert {file.name for file in updated.files} == {"first.txt", "second.pdf"}
    assert {file.mime_type for file in updated.files} == {
        "text/plain",
        "application/pdf",
    }
    assert all(file.id is not None for file in updated.files)
    for file in updated.files:
        stored_file = tmp_path / file.location
        assert stored_file.read_bytes() in {b"first", b"second"}


@pytest.mark.integration
async def test_html_upload_returns_no_content(
    db_session: AsyncSession, users: list[User], tmp_path: Path
):
    creator = users[0]
    source = await create_source(
        db_session,
        SourceCreate(name="HTML upload"),
        creator,
    )

    file_id = uuid.uuid4()
    filesystem = LocalFileSystem(tmp_path)
    response = await upload_source_files_view(
        source.id,
        [UploadFile(file=io.BytesIO(b"content"), filename="file.txt")],
        [file_id],
        db_session,
        filesystem,
        creator,
    )
    retry_response = await upload_source_files_view(
        source.id,
        [UploadFile(file=io.BytesIO(b"content"), filename="file.txt")],
        [file_id],
        db_session,
        filesystem,
        creator,
    )
    files, _ = await get_source_files(db_session, source.id, creator)

    assert response.status_code == retry_response.status_code == 204
    assert [file.name for file in files] == ["file.txt"]


@pytest.mark.integration
async def test_upload_batch_limits_are_enforced(
    db_session: AsyncSession, users: list[User], tmp_path: Path
):
    creator = users[0]
    source = await create_source(
        db_session,
        SourceCreate(name="Upload limits"),
        creator,
    )
    filesystem = LocalFileSystem(tmp_path)

    with pytest.raises(FileUploadException):
        await upload_files_to_source(
            db_session,
            source.id,
            [
                UploadFile(file=io.BytesIO(b"x"), filename=f"{index}.txt")
                for index in range(6)
            ],
            creator,
            filesystem,
        )
    with pytest.raises(FileUploadException):
        await upload_files_to_source(
            db_session,
            source.id,
            [
                UploadFile(
                    file=io.BytesIO(b"x"),
                    size=MAX_UPLOAD_BATCH_BYTES + 1,
                    filename="large.txt",
                )
            ],
            creator,
            filesystem,
        )


@pytest.mark.integration
async def test_source_files_are_paginated(
    db_session: AsyncSession, users: list[User], tmp_path: Path
):
    creator = users[0]
    source = await create_source(
        db_session,
        SourceCreate(name="Paginated files"),
        creator,
    )
    filesystem = LocalFileSystem(tmp_path)
    uploaded = None
    for start in range(0, 12, 5):
        uploaded = await upload_files_to_source(
            db_session,
            source.id,
            [
                UploadFile(
                    file=io.BytesIO(str(index).encode()), filename=f"{index}.txt"
                )
                for index in range(start, min(start + 5, 12))
            ],
            creator,
            filesystem,
        )
    assert uploaded is not None

    first, first_has_more = await get_source_files(
        db_session, source.id, creator, page=1, page_size=5
    )
    second, second_has_more = await get_source_files(
        db_session, source.id, creator, page=2, page_size=5
    )
    third, third_has_more = await get_source_files(
        db_session, source.id, creator, page=3, page_size=5
    )

    assert [len(first), len(second), len(third)] == [5, 5, 2]
    assert [first_has_more, second_has_more, third_has_more] == [True, True, False]
    assert {file.id for file in first + second + third} == {
        file.id for file in uploaded.files
    }


@pytest.mark.integration
async def test_shared_user_can_download_source_file(
    db_session: AsyncSession, users: list[User], tmp_path: Path
):
    creator, viewer, stranger, _ = users
    source = await create_source(
        db_session,
        SourceCreate(name="Shared files", shared_with=[viewer.id]),
        creator,
    )
    filesystem = LocalFileSystem(tmp_path)
    source = await upload_files_to_source(
        db_session,
        source.id,
        [UploadFile(file=io.BytesIO(b"download me"), filename="document.txt")],
        creator,
        filesystem,
    )
    file = source.files[0]

    downloaded_file, content = await read_source_file(
        db_session, source.id, file.id, viewer, filesystem
    )

    assert downloaded_file.id == file.id
    assert content == b"download me"
    response = await download_source_file(
        source.id, file.id, viewer, filesystem, db_session
    )
    assert response.body == b"download me"
    assert response.media_type == "text/plain"
    assert response.headers["content-disposition"].endswith("document.txt")

    with pytest.raises(SourceNotFoundException):
        await read_source_file(db_session, source.id, file.id, stranger, filesystem)
    with pytest.raises(SourceFileNotFoundException):
        await read_source_file(db_session, source.id, uuid.uuid4(), creator, filesystem)


@pytest.mark.integration
async def test_creator_can_delete_source(db_session: AsyncSession, users: list[User]):
    creator = users[0]
    source = await create_source(
        db_session,
        SourceCreate(name="Delete me"),
        creator,
    )

    await delete_source(db_session, source.id, creator)

    with pytest.raises(SourceNotFoundException):
        await get_source(db_session, source.id, creator)


@pytest.mark.integration
async def test_system_sources_are_separate_and_read_only(
    db_session: AsyncSession, users: list[User], tmp_path: Path
):
    creator = users[0]
    system_source = SourceModel(
        name="Converted documents",
        origin=SourceOrigin.SYSTEM,
        created_by_id=creator.id,
        files=[],
        shared_with=[],
    )
    db_session.add(system_source)
    await db_session.flush()

    user_sources, _ = await get_sources(db_session, creator)
    system_sources, _ = await get_sources(
        db_session, creator, origin=SourceOrigin.SYSTEM
    )

    assert system_source not in user_sources
    assert [str(source.id) for source in system_sources] == [str(system_source.id)]
    with pytest.raises(SystemSourceMutationException):
        await update_source(
            db_session, system_source.id, SourceUpdate(name="Renamed"), creator
        )
    with pytest.raises(SystemSourceMutationException):
        await upload_files_to_source(
            db_session,
            system_source.id,
            [UploadFile(file=io.BytesIO(b"content"), filename="file.txt")],
            creator,
            LocalFileSystem(tmp_path),
        )
    with pytest.raises(SystemSourceMutationException):
        await delete_source(db_session, system_source.id, creator)
