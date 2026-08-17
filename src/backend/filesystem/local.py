import shutil
from pathlib import Path

import aiofiles
import aiofiles.os

from .base import FileSystem, WriteData


def _is_stream(data: WriteData) -> bool:
    return hasattr(data, "read")


class LocalFileSystem(FileSystem):
    """FileSystem backed by the local disk.

    Uses ``aiofiles`` for the async methods so file I/O runs on a native
    async-friendly file handle instead of hand-rolled ``asyncio.to_thread``
    wrapping.
    """

    def read(self, path: str | Path) -> bytes:
        resolved = self._resolve(path)
        with open(resolved, "rb") as f:
            return f.read()

    def write(self, path: str | Path, data: WriteData) -> None:
        resolved = self._resolve(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        with open(resolved, "wb") as f:
            if _is_stream(data):
                shutil.copyfileobj(data, f)
            else:
                f.write(data)

    async def read_async(self, path: str | Path) -> bytes:
        resolved = self._resolve(path)
        async with aiofiles.open(resolved, "rb") as f:
            return await f.read()

    async def write_async(self, path: str | Path, data: WriteData) -> None:
        resolved = self._resolve(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(resolved, "wb") as f:
            if _is_stream(data):
                while chunk := data.read(1024 * 1024):
                    await f.write(chunk)
            else:
                await f.write(data)

    def delete(self, path: str | Path) -> None:
        self._resolve(path).unlink()

    async def delete_async(self, path: str | Path) -> None:
        await aiofiles.os.remove(self._resolve(path))
