"""Central import point that registers every model with ``Base.metadata``."""

from ..auth.models import (  # noqa: F401
    InvitationModel,
    UserAuthProviderModel,
    UserPasswordModel,
)
from ..files.models import FileModel  # noqa: F401
from ..knowledge_bases.models import KnowledgeBaseModel  # noqa: F401
from ..mcp.models import (  # noqa: F401
    McpSessionModel,
    McpToolCallModel,
    McpUserModel,
)
from ..sources.models import SourceModel  # noqa: F401
from ..tasks.models import TaskModel  # noqa: F401
from ..users.models import UserModel  # noqa: F401

__all__ = [
    "FileModel",
    "InvitationModel",
    "KnowledgeBaseModel",
    "McpSessionModel",
    "McpToolCallModel",
    "McpUserModel",
    "SourceModel",
    "TaskModel",
    "UserAuthProviderModel",
    "UserModel",
    "UserPasswordModel",
]
