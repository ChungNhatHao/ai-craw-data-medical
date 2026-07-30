import asyncio
import json
from pathlib import Path

from app.core.config import Settings
from app.models.discovery import DiscoveryPolicy
from app.plugins.genre_manuals.plugin import GenreManualsPlugin
from app.repositories.database import Database
from app.repositories.items import ItemRepository
from app.repositories.jobs import JobRepository
from app.services.discovery import DiscoveryService
from tests.support.fixture_page import FixturePage

FIXTURES = Path("tests/fixtures/genre_manuals")
PAGE_1 = "https://www.genre-manuals.com/sites/CLUE/home/medical.html"
PAGE_2 = "https://www.genre-manuals.com/sites/CLUE/home/medical-page-2.html"


def make_plugin() -> GenreManualsPlugin:
    return GenreManualsPlugin(
        base_url="https://www.genre-manuals.com/sites/CLUE/home.html",
        navigation_timeout_ms=1_000,
        selector_timeout_ms=500,
    )


def test_discovery_paginates_deduplicates_persists_and_exports(
    settings: Settings,
) -> None:
    async def scenario() -> None:
        settings.ensure_directories()
        database = Database(settings.database_path, settings.migrations_path)
        await database.initialize()
        job = await JobRepository(database).create("genre_manuals")
        page = FixturePage(
            FIXTURES,
            "disease_list_page1.html",
            initial_url=PAGE_1,
            route_fixtures={PAGE_2: "disease_list_page2.html"},
        )
        service = DiscoveryService(
            make_plugin(),
            ItemRepository(database),
            settings.output_root,
            DiscoveryPolicy(max_items=100, max_pages=10, max_no_new_rounds=2),
        )

        result = await service.run(page, str(job.id))  # type: ignore[arg-type]

        assert result.pages_visited == 2
        assert result.stopped_reason == "last_page"
        assert len(result.items) == 3
        assert len({item.item_id for item in result.items}) == 3
        assert all("utm_" not in str(item.canonical_url) for item in result.items)

        export_path = (
            settings.output_root / "jobs" / str(job.id) / "disease-list.json"
        )
        payload = json.loads(export_path.read_text(encoding="utf-8"))
        assert payload["count"] == 3
        assert len(payload["items"]) == 3

        resume_page = FixturePage(
            FIXTURES,
            "disease_list_page1.html",
            initial_url=PAGE_1,
            route_fixtures={PAGE_2: "disease_list_page2.html"},
        )
        resumed = await service.run(resume_page, str(job.id))  # type: ignore[arg-type]
        assert len(resumed.items) == 3

    asyncio.run(scenario())


def test_discovery_respects_max_items(settings: Settings) -> None:
    async def scenario() -> None:
        settings.ensure_directories()
        database = Database(settings.database_path, settings.migrations_path)
        await database.initialize()
        job = await JobRepository(database).create("genre_manuals")
        page = FixturePage(
            FIXTURES,
            "disease_list_page1.html",
            initial_url=PAGE_1,
        )
        service = DiscoveryService(
            make_plugin(),
            ItemRepository(database),
            settings.output_root,
            DiscoveryPolicy(max_items=1, max_pages=10, max_no_new_rounds=2),
        )

        result = await service.run(page, str(job.id))  # type: ignore[arg-type]

        assert len(result.items) == 1
        assert result.stopped_reason == "max_items"
        assert result.limits_reached == ("max_items",)

    asyncio.run(scenario())

