from fastapi import Depends

from ..config import AppConfig, get_app_config
from .base import FileSystem
from .local import LocalFileSystem


def get_filesystem(
    config: AppConfig = Depends(get_app_config),
) -> FileSystem:
    return LocalFileSystem(config.storage.storage_root)
