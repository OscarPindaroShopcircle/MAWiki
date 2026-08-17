"""Diagnostic records, codes, and per-line suppression.

Jinja discards ``{# ... #}`` comments during lexing, so they never reach the AST.
Suppression is therefore a regex pre-scan of the raw template source, matched
against diagnostic line numbers afterwards.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Attribute resolution
E101 = "E101"  # model has no such attribute
E102 = "E102"  # attribute on a list
E103 = "E103"  # attribute on an opaque (non-model) type
E110 = "E110"  # name not bound in scope

# Structural — always errors, never suppressible
E900 = "E900"  # unsupported Jinja construct
E901 = "E901"  # include cycle

# Discovery / resolution — warnings by default, errors under --strict
W200 = "W200"  # could not resolve a context value to a type
W201 = "W201"  # generic model left unparametrized
W202 = "W202"  # template is never rendered by any discovered route

ALWAYS_ERROR = frozenset({E900, E901})
WARNING_CODES = frozenset({W200, W201, W202})

_ANY_COMMENT = re.compile(r"\{#.*?#\}", re.DOTALL)
_IGNORE_LINE = re.compile(r"\{#-?\s*type:\s*ignore(?:\[([^\]]+)\])?\s*-?#\}")
_IGNORE_FILE = re.compile(r"\{#-?\s*type:\s*ignore-file\s*-?#\}")
_OVERRIDE = re.compile(
    r"\{#-?\s*type:\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*([^\s#]+)\s*-?#\}"
)


@dataclass(frozen=True)
class Diagnostic:
    """One finding, anchored to a template line (Jinja nodes carry no column)."""

    code: str
    template: str
    lineno: int
    message: str
    detail: str = ""
    # Populated when the finding was reached through an {% include %}.
    included_from: tuple[str, int] | None = None

    @property
    def is_warning(self) -> bool:
        return self.code in WARNING_CODES

    def render(self, root: Path | None = None) -> list[str]:
        prefix = self.template if root is None else str(root / self.template)
        head = f"{prefix}:{self.lineno}: {self.code} {self.message}"
        lines = [head]
        if self.detail:
            lines.append(f"    {self.detail}")
        if self.included_from is not None:
            src, src_line = self.included_from
            lines.append(f"    (included from {src}:{src_line})")
        return lines


@dataclass
class Suppressions:
    """Line-level and file-level ignores scraped from one template's source."""

    whole_file: bool = False
    # line number -> set of codes, or an empty set meaning "all codes"
    lines: dict[int, set[str]] = field(default_factory=dict)
    # Lines holding nothing but comments. Only these carry down to the next line;
    # a trailing ignore on a line of markup must not silently cover the line below.
    own_line: set[int] = field(default_factory=set)
    overrides: dict[str, str] = field(default_factory=dict)

    def allows(self, code: str, lineno: int) -> bool:
        """True if a diagnostic at this line/code survives suppression."""
        if code in ALWAYS_ERROR:
            return True
        if self.whole_file:
            return False
        candidates = [lineno]
        if (lineno - 1) in self.own_line:
            candidates.append(lineno - 1)
        for candidate in candidates:
            codes = self.lines.get(candidate)
            if codes is None:
                continue
            if not codes or code in codes:
                return False
        return True


def scan_suppressions(source: str) -> Suppressions:
    result = Suppressions()
    lines = source.splitlines()
    for raw in lines[:5]:
        if _IGNORE_FILE.search(raw):
            result.whole_file = True
            break
    for lineno, raw in enumerate(lines, start=1):
        matched = False
        for match in _IGNORE_LINE.finditer(raw):
            matched = True
            codes = result.lines.setdefault(lineno, set())
            if match.group(1):
                codes.update(part.strip() for part in match.group(1).split(","))
        if matched and not _ANY_COMMENT.sub("", raw).strip():
            result.own_line.add(lineno)
        for match in _OVERRIDE.finditer(raw):
            name, dotted = match.group(1), match.group(2)
            # `type: ignore` also matches the override shape; skip it.
            if name == "ignore":
                continue
            result.overrides[name] = dotted
    return result
