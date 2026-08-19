"""Central import point that registers every model with ``Base.metadata``.

Imported by ``alembic/env.py`` and ``server.py`` so ``Base.metadata`` is fully
populated for ``create_all`` / autogenerate. Do NOT edit by hand — maintained
by ``pre_commits.model_registry``.

Keep ``db/db.py`` and ``db/__init__.py`` free of feature/registry imports to
avoid circular imports: each model module imports ``Base`` itself, so the
order of the lines below does not matter.
"""

from ..auth.models import (  # noqa: F401
    InvitationModel,
    UserAuthProviderModel,
    UserPasswordModel,
)
from ..files.models import FileModel  # noqa: F401
from ..kb.models import KnowledgeBaseModel  # noqa: F401
from ..rag.models import RagModel  # noqa: F401
from ..tasks.models import TaskModel  # noqa: F401
from ..users.models import UserModel  # noqa: F401

__all__ = [
    "FileModel",
    "InvitationModel",
    "KnowledgeBaseModel",
    "RagModel",
    "TaskModel",
    "UserAuthProviderModel",
    "UserModel",
    "UserPasswordModel",
]
