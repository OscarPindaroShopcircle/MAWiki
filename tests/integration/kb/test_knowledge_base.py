import io
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.filesystem import LocalFileSystem
from src.backend.db.enums import UserRole
from src.backend.kb.exception import (
    KnowledgeBaseAccessDeniedException,
    KnowledgeBaseNotFoundException,
)
from src.backend.kb.schemas import KnowledgeBaseCreate, KnowledgeBaseUpdate
from src.backend.kb.service import (
    create_knowledge_base,
    delete_knowledge_base,
    get_knowledge_base,
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
        UploadFile(file=io.BytesIO(b"second"), filename="second.txt"),
    ]

    updated = await upload_files_to_knowledge_base(
        db_session,
        knowledge_base.id,
        uploads,
        creator,
        LocalFileSystem(tmp_path),
    )

    assert {file.name for file in updated.files} == {"first.txt", "second.txt"}
    assert all(file.id is not None for file in updated.files)
    for file in updated.files:
        stored_file = tmp_path / file.location
        assert stored_file.read_bytes() in {b"first", b"second"}


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
