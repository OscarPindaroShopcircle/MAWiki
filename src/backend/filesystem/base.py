from abc import ABC, abstractmethod
from pathlib import Path
from typing import IO

# Anything write() can consume: raw bytes, or a binary file-like object to
# stream from (e.g. an upload's SpooledTemporaryFile) — avoids forcing the
# whole payload into memory as a single bytes object when the caller already
# has a buffer/stream handy.
WriteData = bytes | IO[bytes]


class FileSystem(ABC):
    """Storage-agnostic file access.

    Concrete backends (local disk, S3, Azure Blob, Railway volumes, ...)
    implement the four read/write methods. Callers depend only on this
    interface, so a file can in principle be saved anywhere.

    An optional ``base_path`` makes every operation relative to that root —
    handy for scoping a backend to a directory / bucket-prefix. It may be None.

    Paths accept ``str`` or ``Path``. Be careful with backend-specific path
    semantics: a future S3FileSystem should override ``_resolve`` since S3 keys
    are not filesystem paths (no ``..``, forward-slash separators only, etc.).

    The interface is byte-oriented (``read`` returns bytes, ``write`` accepts
    bytes or a binary IO buffer) for generality; add text-mode helpers on top
    if a caller needs them.
    """

    def __init__(self, base_path: str | Path | None = None):
        self.base_path = Path(base_path) if base_path is not None else None

    def _resolve(self, path: str | Path) -> Path:
        """Resolve ``path`` against ``base_path`` (local/pathlib default)."""
        path = Path(path)
        if self.base_path is None:
            return path
        return self.base_path / path

    @abstractmethod
    def read(self, path: str | Path) -> bytes:
        """Read and return the full contents of ``path``."""

    @abstractmethod
    async def read_async(self, path: str | Path) -> bytes:
        """Async variant of :meth:`read`."""

    @abstractmethod
    def write(self, path: str | Path, data: WriteData) -> None:
        """Write ``data`` to ``path``, overwriting any existing content."""

    @abstractmethod
    async def write_async(self, path: str | Path, data: WriteData) -> None:
        """Async variant of :meth:`write`."""

    @abstractmethod
    def delete(self, path: str | Path) -> None:
        """Remove the file at ``path``."""

    @abstractmethod
    async def delete_async(self, path: str | Path) -> None:
        """Async variant of :meth:`delete`."""
