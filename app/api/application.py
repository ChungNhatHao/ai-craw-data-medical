from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes_health import router as health_router
from app.api.routes_jobs import router as jobs_router
from app.api.routes_ui import router as ui_router
from app.core.config import Settings, get_settings
from app.repositories.database import Database
from app.services.run_manager import RunManager
from app.utils.logging import configure_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(app_settings)
        app_settings.ensure_directories()
        database = Database(
            path=app_settings.database_path,
            migrations_path=app_settings.migrations_path,
        )
        await database.initialize()
        app.state.settings = app_settings
        app.state.database = database
        app.state.run_manager = RunManager(app_settings, database)
        try:
            yield
        finally:
            await app.state.run_manager.close()

    app = FastAPI(
        title="AI Medical Crawler",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(jobs_router, prefix="/api/v1")
    app.include_router(ui_router)
    return app
