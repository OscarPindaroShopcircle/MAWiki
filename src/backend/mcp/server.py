import uuid
from dataclasses import dataclass
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.auth.providers.google import GoogleProvider
from fastmcp.server.dependencies import get_access_token
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import AppConfig
from ..db.db import DatabaseManager
from ..filesystem import LocalFileSystem
from ..knowledge_bases.schemas import KnowledgeBaseSearchRequest
from ..knowledge_bases.service import (
    get_mcp_knowledge_base_file_content,
    get_mcp_knowledge_bases,
    search_knowledge_base,
)
from .auth import workspace_auth_check
from .models import McpSessionModel, McpToolName, McpUserModel
from .service import (
    McpPrincipal,
    get_mcp_session,
    record_mcp_tool_call,
    resolve_mcp_user,
)


@dataclass
class McpApplication:
    app: Any
    database: DatabaseManager

    async def close(self) -> None:
        await self.database.close()


def build_mcp_application(config: AppConfig) -> McpApplication:
    database = DatabaseManager(config.database)
    mcp_config = config.mcp
    tool_auth = None
    auth = None
    if mcp_config.auth_enabled:
        assert (
            mcp_config.google is not None
            and mcp_config.public_url is not None
            and mcp_config.jwt_signing_key is not None
        )
        auth = GoogleProvider(
            client_id=mcp_config.google.client_id,
            client_secret=mcp_config.google.client_secret.get_secret_value(),
            base_url=str(mcp_config.public_url),
            redirect_path=mcp_config.redirect_path,
            required_scopes=["openid", "email", "profile"],
            jwt_signing_key=mcp_config.jwt_signing_key.get_secret_value(),
        )
        tool_auth = workspace_auth_check(mcp_config.google.workspace_domain)
    mcp = FastMCP(config.app_name, auth=auth)

    async def current_user(db: AsyncSession) -> McpUserModel | None:
        if not mcp_config.auth_enabled:
            return None
        token = get_access_token()
        if token is None:
            raise PermissionError("MCP authentication is required")
        try:
            principal = McpPrincipal(
                provider="google",
                subject=str(token.claims["sub"]),
                email=str(token.claims["email"]),
            )
        except KeyError as exc:
            raise PermissionError("Google identity is incomplete") from exc
        return await resolve_mcp_user(db, principal)

    async def session(
        db: AsyncSession, session_id: uuid.UUID | None
    ) -> tuple[McpUserModel | None, McpSessionModel]:
        user = await current_user(db)
        return user, await get_mcp_session(db, user, session_id)

    @mcp.tool(auth=tool_auth)
    async def list_knowledge_bases(session_id: uuid.UUID | None = None) -> dict:
        """List all indexed knowledge bases available to the company."""
        async with database.async_session() as db:
            _, mcp_session = await session(db, session_id)
            knowledge_bases = await get_mcp_knowledge_bases(db)
            await record_mcp_tool_call(
                db, mcp_session, McpToolName.LIST_KNOWLEDGE_BASES
            )
            return {
                "session_id": str(mcp_session.id),
                "knowledge_bases": [
                    {"id": str(knowledge_base.id), "name": knowledge_base.name}
                    for knowledge_base in knowledge_bases
                ],
            }

    @mcp.tool(auth=tool_auth)
    async def search(
        knowledge_base_id: uuid.UUID,
        query: str,
        session_id: uuid.UUID | None = None,
        top_k: int = 10,
    ) -> dict:
        """Search an indexed knowledge base and return relevant text chunks."""
        async with database.async_session() as db:
            _, mcp_session = await session(db, session_id)
            results = await search_knowledge_base(
                db,
                knowledge_base_id,
                KnowledgeBaseSearchRequest(query=query, top_k=top_k),
                LocalFileSystem(config.storage.storage_root),
            )
            await record_mcp_tool_call(
                db,
                mcp_session,
                McpToolName.SEARCH,
                knowledge_base_id=knowledge_base_id,
                query=query,
            )
            return {"session_id": str(mcp_session.id), "results": results}

    @mcp.tool(auth=tool_auth)
    async def fetch_file(
        knowledge_base_id: uuid.UUID,
        source_file_id: uuid.UUID,
        session_id: uuid.UUID | None = None,
    ) -> dict:
        """Return the complete converted text for a source file in a knowledge base."""
        async with database.async_session() as db:
            _, mcp_session = await session(db, session_id)
            file_name, content = await get_mcp_knowledge_base_file_content(
                db,
                knowledge_base_id,
                source_file_id,
                LocalFileSystem(config.storage.storage_root),
            )
            await record_mcp_tool_call(
                db,
                mcp_session,
                McpToolName.FETCH_FILE,
                knowledge_base_id=knowledge_base_id,
                source_file_id=source_file_id,
            )
            return {
                "session_id": str(mcp_session.id),
                "file_name": file_name,
                "content": content,
            }

    return McpApplication(
        app=mcp.http_app(path="/mcp", transport="streamable-http", stateless_http=True),
        database=database,
    )
