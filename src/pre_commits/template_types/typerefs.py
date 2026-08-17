"""Mapping Python annotations onto a small type lattice, and attribute lookup.

Four kinds of reference, deliberately coarse:

``ModelRef``    a Pydantic model — attributes are checked against it
``SeqRef``      a list/sequence — only list methods are valid
``OpaqueRef``   a concrete non-model type (``datetime``, ``uuid.UUID``, ``str``);
                one ``hasattr`` check, then descendants go unchecked
``UnknownRef``  inference was lost; absorbing, never produces a diagnostic

Two codebase-specific decisions, both load-bearing:

* ``Optional`` is stripped unconditionally. That is what lets
  ``{% set t = view.latest_task %}`` followed by ``t.status`` work at all, and it
  is why None-safety is an explicit non-goal (see the package docstring).
* Enums resolve to an *unchecked* opaque. ``AppBaseModel`` sets
  ``use_enum_values=True``, so a field annotated ``TaskStatus`` actually holds a
  plain ``str`` at runtime. Checking attributes against the enum class would be
  wrong in both directions.
"""

from __future__ import annotations

import difflib
import enum
import types
import typing
from dataclasses import dataclass
from functools import lru_cache

from pydantic import BaseModel

_SEQUENCE_ORIGINS = (
    list,
    set,
    tuple,
    frozenset,
    typing.Sequence,
    typing.Iterable,
    typing.List,
    typing.Set,
    typing.Tuple,
)
_MAPPING_ORIGINS = (dict, typing.Mapping, typing.Dict)


@dataclass(frozen=True)
class ModelRef:
    cls: type[BaseModel]

    def label(self) -> str:
        return self.cls.__name__


@dataclass(frozen=True)
class SeqRef:
    elem: "TypeRef"

    def label(self) -> str:
        return f"list[{self.elem.label()}]"


@dataclass(frozen=True)
class OpaqueRef:
    py_type: type | None = None

    def label(self) -> str:
        return self.py_type.__name__ if self.py_type is not None else "unknown"


@dataclass(frozen=True)
class UnknownRef:
    reason: str = ""

    def label(self) -> str:
        return "unknown"


TypeRef = ModelRef | SeqRef | OpaqueRef | UnknownRef

UNKNOWN = UnknownRef()
OPAQUE = OpaqueRef()


def is_pydantic_model(obj: object) -> bool:
    return isinstance(obj, type) and issubclass(obj, BaseModel)


def unparametrized_typevars(cls: type[BaseModel]) -> tuple[typing.TypeVar, ...]:
    """TypeVars still free on a generic model (``PaginatedResponse`` vs ``[X]``)."""
    meta = getattr(cls, "__pydantic_generic_metadata__", None)
    if not meta:
        return ()
    if meta.get("args"):
        return ()
    return tuple(meta.get("parameters") or ())


def normalize(annotation: object) -> TypeRef:
    """Collapse a Python annotation to a ``TypeRef``."""
    if annotation is None or annotation is type(None):
        return UNKNOWN

    origin = typing.get_origin(annotation)

    if origin is typing.Annotated:
        args = typing.get_args(annotation)
        return normalize(args[0]) if args else UNKNOWN

    if origin in (typing.Union, types.UnionType):
        members = [a for a in typing.get_args(annotation) if a is not type(None)]
        if len(members) == 1:
            return normalize(members[0])
        return UnknownRef("union of multiple types")

    if origin is not None:
        if origin in _SEQUENCE_ORIGINS:
            args = typing.get_args(annotation)
            return SeqRef(normalize(args[0]) if args else UNKNOWN)
        if origin in _MAPPING_ORIGINS:
            return OpaqueRef(dict)
        if is_pydantic_model(origin):
            # A parametrized generic model: pydantic hands back a concrete class.
            return ModelRef(origin)
        return UnknownRef(f"unsupported generic {origin!r}")

    if isinstance(annotation, typing.TypeVar):
        return UnknownRef("unparametrized type variable")

    if is_pydantic_model(annotation):
        return ModelRef(annotation)

    if isinstance(annotation, type):
        if issubclass(annotation, enum.Enum):
            # use_enum_values=True -> a plain value at runtime, so stop checking.
            return OPAQUE
        return OpaqueRef(annotation)

    return UnknownRef(f"unrecognized annotation {annotation!r}")


@lru_cache(maxsize=512)
def _property_hint(cls: type, name: str) -> object | None:
    """Return type of a ``property``/``cached_property`` found on the MRO."""
    for klass in cls.__mro__:
        member = vars(klass).get(name)
        if member is None:
            continue
        getter = None
        if isinstance(member, property):
            getter = member.fget
        else:  # functools.cached_property and lookalikes
            getter = getattr(member, "func", None)
        if getter is None:
            return None
        try:
            return typing.get_type_hints(getter).get("return")
        except Exception:
            return None
    return None


@lru_cache(maxsize=512)
def _known_names(cls: type[BaseModel]) -> tuple[str, ...]:
    """Field and property names, for 'did you mean' suggestions."""
    names = set(cls.model_fields)
    names.update(getattr(cls, "model_computed_fields", {}) or {})
    for klass in cls.__mro__:
        if klass is BaseModel or klass is object:
            continue
        for name, member in vars(klass).items():
            if name.startswith("_"):
                continue
            if isinstance(member, property) or hasattr(member, "func"):
                names.add(name)
    return tuple(sorted(names))


@dataclass(frozen=True)
class AttrResult:
    ref: TypeRef
    code: str | None = None
    message: str = ""
    hint: str = ""


def _suggest(name: str, candidates: tuple[str, ...]) -> str:
    matches = difflib.get_close_matches(name, candidates, n=1, cutoff=0.6)
    if matches:
        return f"did you mean '{matches[0]}'?"
    return ""


def getattr_type(ref: TypeRef, name: str) -> AttrResult:
    """Resolve ``<ref>.<name>``, reporting a diagnostic code when invalid."""
    if isinstance(ref, UnknownRef):
        return AttrResult(UNKNOWN)

    if isinstance(ref, ModelRef):
        cls = ref.cls
        field = cls.model_fields.get(name)
        if field is not None:
            return AttrResult(normalize(field.annotation))

        computed = (getattr(cls, "model_computed_fields", {}) or {}).get(name)
        if computed is not None:
            return AttrResult(normalize(getattr(computed, "return_type", None)))

        hint = _property_hint(cls, name)
        if hint is not None:
            return AttrResult(normalize(hint))

        if hasattr(cls, name):
            # A real method or class attribute (model_dump, serializable_dict...).
            return AttrResult(OPAQUE)

        known = _known_names(cls)
        suggestion = _suggest(name, known)
        # Aliases are a serialization concern only; camelCase access is a real bug.
        if not suggestion and cls.model_config.get("alias_generator") is not None:
            snake = "".join(
                f"_{ch.lower()}" if ch.isupper() else ch for ch in name
            ).lstrip("_")
            if snake in known:
                suggestion = (
                    f"'{snake}' exists; aliases apply to (de)serialization, "
                    "not attribute access"
                )
        return AttrResult(
            UNKNOWN,
            code="E101",
            message=f"{cls.__name__} has no attribute '{name}'",
            hint=suggestion,
        )

    if isinstance(ref, SeqRef):
        if hasattr([], name):
            return AttrResult(OPAQUE)
        return AttrResult(
            UNKNOWN,
            code="E102",
            message=f"'{name}' is not an attribute of a list",
            hint=f"iterate it first, or use one of {ref.label()}'s elements",
        )

    # OpaqueRef: one check against a known concrete type, then stop descending.
    if ref.py_type is None:
        return AttrResult(OPAQUE)
    if hasattr(ref.py_type, name):
        return AttrResult(OPAQUE)
    return AttrResult(
        UNKNOWN,
        code="E103",
        message=f"{ref.py_type.__name__} has no attribute '{name}'",
        hint=_suggest(
            name, tuple(a for a in dir(ref.py_type) if not a.startswith("_"))
        ),
    )
