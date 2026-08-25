from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .auth.routes.auth import router as auth_router
from .auth.routes.invitations import router as invitation_router
from .config import AppConfig, get_app_config
from .db.db import DatabaseManager
from .log import setup_logging
from .users.routes import router as users_router
from .kb.routes import router as kb_router
from .mcp.server import build_mcp_application
from .rag.routes import router as rag_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = getattr(app.state, "config", None)
    if config is None:
        config = get_app_config()
    db_manager = DatabaseManager(config.database, echo=config.logging.db_echo)
    mcp_application = getattr(app.state, "mcp_application", None)
    try:
        if mcp_application is None:
            yield
        else:
            async with mcp_application.app.router.lifespan_context(mcp_application.app):
                yield
    finally:
        if mcp_application is not None:
            await mcp_application.close()
        await db_manager.close()


def create_app(config: AppConfig | None = None) -> FastAPI:
    if config is None:
        config = get_app_config()

    setup_logging(config.logging.level, json_mode=config.logging.json_mode)

    app = FastAPI(
        title="Fantasy Backend",
        lifespan=lifespan,
    )
    app.state.config = config
    if config.mcp.enabled:
        app.state.mcp_application = build_mcp_application(config)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=config.cors_allow_credentials,
        allow_methods=config.cors_allow_methods,
        allow_headers=config.cors_allow_headers,
    )

    if config.frontend and config.frontend.enabled:
        # JinjaX generates asset URLs like /static/components/common/button.css.
        # Mount the components directory BEFORE the generic /static mount so
        # the more specific prefix takes priority.
        app.mount(
            "/static/components",
            StaticFiles(directory=config.frontend.components_dir),
            name="components-static",
        )
        app.mount(
            "/static", StaticFiles(directory=config.frontend.static_dir), name="static"
        )

    # normal router import
    app.include_router(users_router)
    app.include_router(auth_router)
    app.include_router(invitation_router)
    app.include_router(kb_router)
    app.include_router(rag_router)

    # Importing the registry registers every model with Base.metadata so
    # DatabaseManager.initialize_tables() / alembic see all tables, including
    # features that have no router mounted (e.g. files/).
    from .db import registry  # noqa: F401, PLC0415

    # optional frontend routes
    if config.frontend and config.frontend.enabled:
        from .auth.views import router as auth_views_router  # noqa: PLC0415
        from .users.views import router as users_views_router  # noqa: PLC0415
        from .kb.views import router as kb_views_router  # noqa: PLC0415
        from .rag.views import router as rag_views_router  # noqa: PLC0415
        from .views import router as views_router  # noqa: PLC0415

        app.include_router(auth_views_router)
        app.include_router(users_views_router)
        app.include_router(kb_views_router)
        app.include_router(rag_views_router)
        app.include_router(views_router)

        # Dev-only: mount the component showcase
        if config.env == "dev":
            from .showcase.views import router as showcase_router  # noqa: PLC0415

            app.include_router(showcase_router)

    # health check endpoint
    @app.get("/ping")
    async def ping():
        return {"status": "ok"}

    mcp_application = getattr(app.state, "mcp_application", None)
    if mcp_application is not None:
        app.mount("/", mcp_application.app)

    return app


if __name__ == "__main__":
    config = get_app_config()
    app = create_app(config)
