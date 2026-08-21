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
from src.backend.kb.constants import MAX_UPLOAD_BATCH_BYTES
from src.backend.kb.exception import (
    FileUploadException,
    KnowledgeBaseAccessDeniedException,
    KnowledgeBaseFileNotFoundException,
    KnowledgeBaseNotFoundException,
)
from src.backend.kb.routes import download_knowledge_base_file
from src.backend.kb.schemas import KnowledgeBaseCreate, KnowledgeBaseUpdate
from src.backend.kb.views import upload_knowledge_base_files_view
from src.backend.kb.service import (
    create_knowledge_base,
    delete_knowledge_base,
    get_knowledge_base,
    get_knowledge_base_files,
    read_knowledge_base_file,
    update_knowledge_base,
    upload_files_to_knowledge_base,
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
async def test_knowledge_base_visibility_and_mutation_authorization(
    db_session: AsyncSession, users: list[User]
):
    creator, viewer, stranger, admin = users
    knowledge_base = await create_knowledge_base(
        db_session,
        KnowledgeBaseCreate(name="Shared KB", shared_with=[viewer.id]),
        creator,
    )

    assert (
        await get_knowledge_base(db_session, knowledge_base.id, creator)
    ).name == "Shared KB"
    assert (
        await get_knowledge_base(db_session, knowledge_base.id, viewer)
    ).name == "Shared KB"
    with pytest.raises(KnowledgeBaseNotFoundException):
        await get_knowledge_base(db_session, knowledge_base.id, stranger)

    with pytest.raises(KnowledgeBaseAccessDeniedException):
        await update_knowledge_base(
            db_session,
            knowledge_base.id,
            KnowledgeBaseUpdate(name="Not allowed"),
            viewer,
        )

    updated = await update_knowledge_base(
        db_session,
        knowledge_base.id,
        KnowledgeBaseUpdate(name="Updated KB"),
        creator,
    )
    assert updated.name == "Updated KB"

    admin_updated = await update_knowledge_base(
        db_session,
        knowledge_base.id,
        KnowledgeBaseUpdate(name="Admin Updated KB"),
        admin,
    )
    assert admin_updated.name == "Admin Updated KB"

    with pytest.raises(KnowledgeBaseAccessDeniedException):
        await delete_knowledge_base(db_session, knowledge_base.id, viewer)


@pytest.mark.integration
async def test_upload_files_persists_metadata_and_association(
    db_session: AsyncSession, users: list[User], tmp_path: Path
):
    creator = users[0]
    knowledge_base = await create_knowledge_base(
        db_session,
        KnowledgeBaseCreate(name="Uploads"),
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

    updated = await upload_files_to_knowledge_base(
        db_session,
        knowledge_base.id,
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
    knowledge_base = await create_knowledge_base(
        db_session,
        KnowledgeBaseCreate(name="HTML upload"),
        creator,
    )

    file_id = uuid.uuid4()
    filesystem = LocalFileSystem(tmp_path)
    response = await upload_knowledge_base_files_view(
        knowledge_base.id,
        [UploadFile(file=io.BytesIO(b"content"), filename="file.txt")],
        [file_id],
        db_session,
        filesystem,
        creator,
    )
    retry_response = await upload_knowledge_base_files_view(
        knowledge_base.id,
        [UploadFile(file=io.BytesIO(b"content"), filename="file.txt")],
        [file_id],
        db_session,
        filesystem,
        creator,
    )
    files, _ = await get_knowledge_base_files(db_session, knowledge_base.id, creator)

    assert response.status_code == retry_response.status_code == 204
    assert [file.name for file in files] == ["file.txt"]


@pytest.mark.integration
async def test_upload_batch_limits_are_enforced(
    db_session: AsyncSession, users: list[User], tmp_path: Path
):
    creator = users[0]
    knowledge_base = await create_knowledge_base(
        db_session,
        KnowledgeBaseCreate(name="Upload limits"),
        creator,
    )
    filesystem = LocalFileSystem(tmp_path)

    with pytest.raises(FileUploadException):
        await upload_files_to_knowledge_base(
            db_session,
            knowledge_base.id,
            [
                UploadFile(file=io.BytesIO(b"x"), filename=f"{index}.txt")
                for index in range(6)
            ],
            creator,
            filesystem,
        )
    with pytest.raises(FileUploadException):
        await upload_files_to_knowledge_base(
            db_session,
            knowledge_base.id,
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
async def test_knowledge_base_files_are_paginated(
    db_session: AsyncSession, users: list[User], tmp_path: Path
):
    creator = users[0]
    knowledge_base = await create_knowledge_base(
        db_session,
        KnowledgeBaseCreate(name="Paginated files"),
        creator,
    )
    filesystem = LocalFileSystem(tmp_path)
    uploaded = None
    for start in range(0, 12, 5):
        uploaded = await upload_files_to_knowledge_base(
            db_session,
            knowledge_base.id,
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

    first, first_has_more = await get_knowledge_base_files(
        db_session, knowledge_base.id, creator, page=1, page_size=5
    )
    second, second_has_more = await get_knowledge_base_files(
        db_session, knowledge_base.id, creator, page=2, page_size=5
    )
    third, third_has_more = await get_knowledge_base_files(
        db_session, knowledge_base.id, creator, page=3, page_size=5
    )

    assert [len(first), len(second), len(third)] == [5, 5, 2]
    assert [first_has_more, second_has_more, third_has_more] == [True, True, False]
    assert {file.id for file in first + second + third} == {
        file.id for file in uploaded.files
    }


@pytest.mark.integration
async def test_shared_user_can_download_knowledge_base_file(
    db_session: AsyncSession, users: list[User], tmp_path: Path
):
    creator, viewer, stranger, _ = users
    knowledge_base = await create_knowledge_base(
        db_session,
        KnowledgeBaseCreate(name="Shared files", shared_with=[viewer.id]),
        creator,
    )
    filesystem = LocalFileSystem(tmp_path)
    knowledge_base = await upload_files_to_knowledge_base(
        db_session,
        knowledge_base.id,
        [UploadFile(file=io.BytesIO(b"download me"), filename="document.txt")],
        creator,
        filesystem,
    )
    file = knowledge_base.files[0]

    downloaded_file, content = await read_knowledge_base_file(
        db_session, knowledge_base.id, file.id, viewer, filesystem
    )

    assert downloaded_file.id == file.id
    assert content == b"download me"
    response = await download_knowledge_base_file(
        knowledge_base.id, file.id, viewer, filesystem, db_session
    )
    assert response.body == b"download me"
    assert response.media_type == "text/plain"
    assert response.headers["content-disposition"].endswith("document.txt")

    with pytest.raises(KnowledgeBaseNotFoundException):
        await read_knowledge_base_file(
            db_session, knowledge_base.id, file.id, stranger, filesystem
        )
    with pytest.raises(KnowledgeBaseFileNotFoundException):
        await read_knowledge_base_file(
            db_session, knowledge_base.id, uuid.uuid4(), creator, filesystem
        )


@pytest.mark.integration
async def test_creator_can_delete_knowledge_base(
    db_session: AsyncSession, users: list[User]
):
    creator = users[0]
    knowledge_base = await create_knowledge_base(
        db_session,
        KnowledgeBaseCreate(name="Delete me"),
        creator,
    )

    await delete_knowledge_base(db_session, knowledge_base.id, creator)

    with pytest.raises(KnowledgeBaseNotFoundException):
        await get_knowledge_base(db_session, knowledge_base.id, creator)
