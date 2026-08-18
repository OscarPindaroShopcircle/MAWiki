from typing import AsyncGenerator
from jinjax.catalog import Catalog
from sqlalchemy.ext.asyncio import AsyncSession
from .config import get_app_config, AppConfig
from .db.db import DatabaseManager
from .jinja import get_catalog, _build_templates
from fastapi import Depends


def get_db_manager(config: AppConfig = Depends(get_app_config)) -> DatabaseManager:
    db_manager = DatabaseManager(config.database)
    return db_manager


async def get_db_session(
    db_manager: DatabaseManager = Depends(get_db_manager),
) -> AsyncGenerator[AsyncSession, None]:
    """Yield a database session that auto-commits on success or rollbacks on failure.

    The caller should NOT call commit() or rollback() — the dependency handles it.
    """
    session = db_manager.async_session_maker()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_config() -> AppConfig:
    return get_app_config()


def get_catalog_dep(config: AppConfig = Depends(get_app_config)) -> Catalog:
    """Return the shared JinjaX ``Catalog`` instance.

    Requires ``frontend`` to be configured — a view route depending on this
    only runs when the frontend is enabled.
    """
    if config.frontend is None:
        raise RuntimeError(
            "Catalog requested but no `frontend` config is set; "
            "add a `frontend:` block to config.yaml."
        )
    return get_catalog(
        config.frontend.components_dir,
        env=config.env,
        app_name=config.app_name,
    )


def get_templates(config: AppConfig = Depends(get_app_config)):
    """Return the shared ``Jinja2Templates`` instance, if configured.

    Only builds when ``templates_dir`` is set in the frontend config.
    """
    if config.frontend is None or config.frontend.templates_dir is None:
        raise RuntimeError(
            "Templates requested but `templates_dir` is not set; "
            "add it to the `frontend:` block in config.yaml."
        )
    return _build_templates(config.frontend.templates_dir)
