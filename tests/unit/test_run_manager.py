import asyncio

import pytest

from app.core.config import Settings
from app.models.run import RunRequest
from app.repositories.database import Database
from app.services.run_manager import RunManager


def test_run_manager_rejects_unapproved_or_external_target(
    settings: Settings,
) -> None:
    async def scenario() -> None:
        settings.ensure_directories()
        database = Database(settings.database_path, settings.migrations_path)
        await database.initialize()
        manager = RunManager(settings, database)

        with pytest.raises(ValueError, match="xác nhận"):
            await manager.start(
                RunRequest(
                    url="https://www.genre-manuals.com/sites/CLUE/home.html",
                    username="user",
                    password="secret",
                    authorization_confirmed=False,
                )
            )
        with pytest.raises(ValueError, match="genre-manuals.com"):
            await manager.start(
                RunRequest(
                    url="https://example.test/",
                    username="user",
                    password="secret",
                    authorization_confirmed=True,
                )
            )
        with pytest.raises(ValueError, match="chưa được bật"):
            await manager.start(
                RunRequest(
                    url="https://www.genre-manuals.com/sites/CLUE/home.html",
                    username="user",
                    password="secret",
                    authorization_confirmed=True,
                    agentic_discovery=True,
                )
            )
        with pytest.raises(ValueError, match="Agentic Parsing"):
            await manager.start(
                RunRequest(
                    url="https://www.genre-manuals.com/sites/CLUE/home.html",
                    username="user",
                    password="secret",
                    authorization_confirmed=True,
                    agentic_parsing=True,
                )
            )

        assert "secret" not in repr(
            RunRequest(
                url="https://www.genre-manuals.com/sites/CLUE/home.html",
                username="user",
                password="secret",
                authorization_confirmed=True,
            )
        )
        await manager.close()

    asyncio.run(scenario())
