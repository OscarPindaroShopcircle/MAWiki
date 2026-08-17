"""Enumerations shared across the database layer or by multiple features.

Backed by SQLAlchemy `Enum(...)` columns on the models. We prefer real enums
over free string columns so the set of valid values is enforced at the DB level.

Feature-only enums (e.g. ``TaskStatus``, ``StorageType``) live next to their
owning model in ``<feature>/models.py``; only cross-feature or infrastructure
enums live here.
"""

from enum import Enum


class FeedbackValue(str, Enum):
    """Thumbs up / thumbs down feedback value.

    Used by ``BinaryFeedbackMixin`` on the ranking and generative output
    tables — the human "OK / NOT OK" judgment on a prediction (F7).
    """

    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"


class DataSplit(str, Enum):
    """Train/test split assignment for a judgement.

    TRAIN — used for model training (example sampling, prompt construction)
    VAL   — reserved for future validation split (not used yet)
    TEST  — held out for evaluation only

    NULL on the column means the judgement has not been assigned to a split yet.
    """

    TRAIN = "train"
    VAL = "val"
    TEST = "test"


class UserRole(str, Enum):
    """User role for authorization.

    ADMIN  — full access, can view admin pages and create invitations
    MEMBER — default role for invited users
    """

    ADMIN = "admin"
    MEMBER = "member"
