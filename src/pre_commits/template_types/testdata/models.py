"""Fixture models for the checker's own tests.

Deliberately separate from ``backend.*`` schemas so that legitimate changes to the
app's models cannot break the analyzer's unit tests.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Generic, List, Optional, TypeVar

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

T = TypeVar("T")


class Colour(str, enum.Enum):
    RED = "RED"
    BLUE = "BLUE"


class Leaf(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    name: str
    created_at: datetime
    colour: Colour
    note: Optional[str] = None


class Branch(BaseModel):
    leaf: Leaf
    leaves: List[Leaf] = []
    maybe_leaf: Leaf | None = None

    @property
    def newest(self) -> Leaf | None:
        """A property rather than a field — must still resolve."""
        return self.leaves[-1] if self.leaves else None


class Page(BaseModel, Generic[T]):
    data: List[T]
    page: int


class TabAlpha(BaseModel):
    alpha: str


class TabBeta(BaseModel):
    beta: str
