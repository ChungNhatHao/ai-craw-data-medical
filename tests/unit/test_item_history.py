import asyncio

from app.core.config import Settings
from app.plugins.fake import FakeSitePlugin
from app.repositories.database import Database
from app.repositories.items import ItemRepository
from app.repositories.jobs import JobRepository


def test_completed_item_history_only_returns_parsed_same_plugin(
    settings: Settings,
) -> None:
    async def scenario() -> None:
        settings.ensure_directories()
        database = Database(settings.database_path, settings.migrations_path)
        await database.initialize()
        jobs = JobRepository(database)
        items = ItemRepository(database)
        alpha, beta = await FakeSitePlugin().discover_demo_items()

        completed_job = await jobs.create("fake")
        await items.upsert_discovered(
            str(completed_job.id),
            [alpha, beta],
        )
        await items.mark_parsed(
            str(completed_job.id),
            alpha.item_id,
            "items/alpha",
        )
        await items.mark_fetch_failed(
            str(completed_job.id),
            beta.item_id,
            "TEST_RETRYABLE",
        )

        other_plugin_job = await jobs.create("other")
        await items.upsert_discovered(str(other_plugin_job.id), [beta])
        await items.mark_parsed(
            str(other_plugin_job.id),
            beta.item_id,
            "items/beta",
        )

        current_job = await jobs.create("fake")
        completed = await items.list_completed_item_ids(
            plugin="fake",
            exclude_job_id=str(current_job.id),
        )

        assert completed == {alpha.item_id}
        assert (
            await items.list_completed_item_ids(
                plugin="fake",
                exclude_job_id=str(completed_job.id),
            )
            == set()
        )

    asyncio.run(scenario())
