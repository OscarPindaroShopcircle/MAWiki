"""AI-specific mixins: model predictions, ground truths, and feedback.

These are building blocks to be composed onto concrete models later — they
are deliberately NOT models themselves. A single row can mix several of them
(e.g. ModelNameMixin + ClassificationOutputMixin + ExecutionTimeMixin, the
latter from ``mixins.py``).
"""

from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import MappedColumn, mapped_column

from .enums import FeedbackValue

# Classification labels are short, closed-vocabulary strings — capped tight
# (not 255) so indexes/filters on them stay fast and low-memory.
CLASSIFICATION_LABEL_LENGTH = 32


class ModelNameMixin:
    """Associates a row with the AI model that produced it.

    Kept as a plain string for simplicity (model registry can come later).
    """

    model_name: MappedColumn[str] = mapped_column(
        String(255),
        nullable=False,
    )


class ClassificationOutputMixin:
    """A single classification prediction, optionally paired with ground truth.

    * predicted_class    → what the model predicted
    * ground_truth_class → the correct label, if/when known (optional)
    * score              → model confidence for the prediction (optional)
    """

    predicted_class: MappedColumn[str] = mapped_column(
        String(CLASSIFICATION_LABEL_LENGTH),
        nullable=False,
    )
    ground_truth_class: MappedColumn[str | None] = mapped_column(
        String(CLASSIFICATION_LABEL_LENGTH),
        nullable=True,
    )
    score: MappedColumn[float | None] = mapped_column(
        Float,
        nullable=True,
    )


class GenerationOutputMixin:
    """A free-text generation, optionally paired with a reference/ground truth.

    Uses TEXT (unbounded) since generated content has no natural length cap.
    """

    predicted_text: MappedColumn[str] = mapped_column(
        Text,
        nullable=False,
    )
    ground_truth_text: MappedColumn[str | None] = mapped_column(
        Text,
        nullable=True,
    )


class BinaryFeedbackMixin:
    """Thumbs up / thumbs down feedback on a row.

    Nullable so a row can exist before any feedback is given:
        POSITIVE → thumbs up
        NEGATIVE → thumbs down
        None     → no feedback yet
    """

    feedback: MappedColumn[FeedbackValue | None] = mapped_column(
        Enum(FeedbackValue),
        nullable=True,
        default=None,
    )


class FeedbackAuditMixin:
    """Who made the human judgment on this row, and when.

    The audit counterpart to the *value* columns above
    (``ClassificationOutputMixin.ground_truth_class``,
    ``BinaryFeedbackMixin.feedback``): those say *what* the human decided, these
    say *who* and *when*. Deliberately one shared vocabulary across every
    output table so evaluation code (F8) doesn't have to know which archetype
    it's reading.

    Both nullable — a prediction exists long before anyone judges it. A row
    with ``feedback_set_at IS NULL`` is un-rated, which is exactly how the
    rating queue finds its next candidate.

    An FK to ``users.id`` (not a free string like ``AuditMixin.created_by``)
    because per ``docs/feature_requests/models.md`` we need to know which user
    gave the feedback — *especially* the feedback — so it should be a real
    reference the DB can enforce.
    """

    feedback_set_by: MappedColumn[int | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
        default=None,
    )
    feedback_set_at: MappedColumn[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )


class IntegerFeedbackMixin:
    """Integer-valued feedback (e.g. a 1–5 rating).

    Nullable so a row can exist before it has been voted on. Add a
    CheckConstraint on the concrete model if you want to bound the range.
    """

    vote: MappedColumn[int | None] = mapped_column(
        Integer,
        nullable=True,
        default=None,
    )


class RetrievalOutputMixin:
    """A retrieval result: the query that triggered it and what came back.

    * query_text     → the text that drove the retrieval
    * retrieved_text → the retrieved chunk/document
    * score          → similarity/relevance score (optional)
    """

    query_text: MappedColumn[str] = mapped_column(
        Text,
        nullable=False,
    )
    retrieved_text: MappedColumn[str] = mapped_column(
        Text,
        nullable=False,
    )
    score: MappedColumn[float | None] = mapped_column(
        Float,
        nullable=True,
    )
