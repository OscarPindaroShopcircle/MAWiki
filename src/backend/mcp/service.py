import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .exceptions import McpSessionAccessDeniedException
from .models import McpSessionModel, McpToolCallModel, McpToolName, McpUserModel


@dataclass(frozen=True)
class McpPrincipal:
    provider: str
    subject: str
    email: str


async def resolve_mcp_user(db: AsyncSession, principal: McpPrincipal) -> McpUserModel:
    result = await db.execute(
        select(McpUserModel).where(
            McpUserModel.provider == principal.provider,
            McpUserModel.provider_subject == principal.subject,
        )
    )
    user = result.scalar_one_or_none()
    now = datetime.now(UTC)
    if user is None:
        user = McpUserModel(
            provider=principal.provider,
            provider_subject=principal.subject,
            email=principal.email,
            last_seen_at=now,
        )
        db.add(user)
    else:
        user.email = principal.email
        user.last_seen_at = now
    await db.flush()
    return user


async def get_mcp_session(
    db: AsyncSession,
    user: McpUserModel | None,
    session_id: uuid.UUID | None,
) -> McpSessionModel:
    if session_id is None:
        session = McpSessionModel(mcp_user_id=user.id if user else None)
        db.add(session)
        await db.flush()
        return session

    session = await db.get(McpSessionModel, session_id)
    if session is None or session.mcp_user_id != (user.id if user else None):
        raise McpSessionAccessDeniedException("MCP session is not available")
    return session


async def record_mcp_tool_call(
    db: AsyncSession,
    session: McpSessionModel,
    tool: McpToolName,
    *,
    rag_id: uuid.UUID | None = None,
    source_file_id: uuid.UUID | None = None,
    query: str | None = None,
) -> McpToolCallModel:
    call = McpToolCallModel(
        session_id=session.id,
        tool=tool,
        rag_id=rag_id,
        source_file_id=source_file_id,
        query=query,
    )
    db.add(call)
    await db.flush()
    return call
