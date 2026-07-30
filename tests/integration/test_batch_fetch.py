import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from app.core.config import Settings
from app.core.errors import CrawlerError, ErrorCode
from app.core.ids import build_item_id
from app.models.batch import BatchPolicy
from app.models.crawl import JobStatus
from app.models.discovery import DiscoveredItem
from app.repositories.database import Database
from app.repositories.items import ItemRepository
from app.repositories.jobs import JobRepository
from app.services.batch import BatchFetchService
from app.storage.artifacts import ArtifactStore


def make_item(name: str) -> DiscoveredItem:
    url = f"https://example.test/diseases/{name}"
    return DiscoveredItem(
        item_id=build_item_id("fake", url),
        source_url=url,
        canonical_url=url,
        title_hint=name.title(),
        discovery_page="https://example.test/diseases",
    )


class FakeBatchDetailFetch:
    def __init__(
        self,
        items: ItemRepository,
        *,
        fail_names: frozenset[str] = frozenset(),
        after_success: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.items = items
        self.fail_names = fail_names
        self.after_success = after_success
        self.calls: list[str] = []

    async def run(
        self,
        page: Any,
        *,
        job_id: str,
        item: DiscoveredItem,
    ) -> None:
        del page
        name = item.title_hint or ""
        self.calls.append(name)
        if name.lower() in self.fail_names:
            await self.items.mark_fetching(job_id, item.item_id)
            await self.items.mark_fetch_failed(
                job_id,
                item.item_id,
                ErrorCode.PAGE_TYPE_UNKNOWN.value,
            )
            raise CrawlerError(
                ErrorCode.PAGE_TYPE_UNKNOWN,
                "Fixture item is not a disease detail",
            )
        await self.items.mark_fetching(job_id, item.item_id)
        await self.items.mark_fetched(
            job_id,
            item.item_id,
            f"jobs/{job_id}/items/{name.lower()}",
        )
        if self.after_success is not None:
            callback = self.after_success
            self.after_success = None
            await callback()


async def prepare(
    settings: Settings,
    names: tuple[str, ...],
) -> tuple[str, JobRepository, ItemRepository, ArtifactStore]:
    settings.ensure_directories()
    database = Database(settings.database_path, settings.migrations_path)
    await database.initialize()
    jobs = JobRepository(database)
    job = await jobs.create("fake")
    items = ItemRepository(database)
    await items.upsert_discovered(
        str(job.id),
        [make_item(name) for name in names],
    )
    return str(job.id), jobs, items, ArtifactStore(settings.output_root)


def test_batch_continues_after_one_item_failure(settings: Settings) -> None:
    async def scenario() -> None:
        job_id, jobs, items, artifacts = await prepare(
            settings,
            ("alpha", "beta", "gamma"),
        )
        detail = FakeBatchDetailFetch(items, fail_names=frozenset({"beta"}))
        batch = BatchFetchService(
            jobs=jobs,
            items=items,
            artifacts=artifacts,
            detail_fetch=detail,  # type: ignore[arg-type]
            policy=BatchPolicy(max_items=10),
        )

        result = await batch.run(object(), job_id=job_id)  # type: ignore[arg-type]

        assert result.status is JobStatus.COMPLETED_WITH_ERRORS
        assert result.processed_count == 3
        assert result.fetched_count == 2
        assert result.failed_count == 1
        assert detail.calls == ["Alpha", "Beta", "Gamma"]
        assert await items.count_by_status(job_id) == {
            "fetched": 2,
            "retryable_failed": 1,
        }

    asyncio.run(scenario())


def test_graceful_pause_finishes_checkpoint_then_resume_skips_fetched(
    settings: Settings,
) -> None:
    async def scenario() -> None:
        job_id, jobs, items, artifacts = await prepare(
            settings,
            ("alpha", "beta", "gamma"),
        )

        async def request_pause() -> None:
            await jobs.request_pause(job_id)

        first_detail = FakeBatchDetailFetch(
            items,
            after_success=request_pause,
        )
        first_batch = BatchFetchService(
            jobs=jobs,
            items=items,
            artifacts=artifacts,
            detail_fetch=first_detail,  # type: ignore[arg-type]
            policy=BatchPolicy(max_items=10),
        )
        paused = await first_batch.run(  # type: ignore[arg-type]
            object(),
            job_id=job_id,
        )

        assert paused.status is JobStatus.PAUSED
        assert paused.processed_count == 1
        assert paused.remaining_count == 2
        assert first_detail.calls == ["Alpha"]

        resumed_detail = FakeBatchDetailFetch(items)
        resumed_batch = BatchFetchService(
            jobs=jobs,
            items=items,
            artifacts=artifacts,
            detail_fetch=resumed_detail,  # type: ignore[arg-type]
            policy=BatchPolicy(max_items=10),
        )
        resumed = await resumed_batch.run(  # type: ignore[arg-type]
            object(),
            job_id=job_id,
        )

        assert resumed.status is JobStatus.COMPLETED
        assert resumed.fetched_count == 2
        assert resumed_detail.calls == ["Beta", "Gamma"]
        assert await items.count_by_status(job_id) == {"fetched": 3}

    asyncio.run(scenario())


def test_restart_reconciles_fetching_items_from_artifacts(settings: Settings) -> None:
    async def scenario() -> None:
        job_id, jobs, items, artifacts = await prepare(
            settings,
            ("alpha", "beta"),
        )
        alpha = make_item("alpha")
        beta = make_item("beta")
        _, artifact_dir = artifacts.persist_raw(
            job_id=job_id,
            plugin="fake",
            item=alpha,
            html="<html><main>Alpha raw</main></html>",
            screenshot=None,
            confidence=1,
        )
        await items.mark_fetching(job_id, alpha.item_id)
        await items.mark_fetching(job_id, beta.item_id)

        detail = FakeBatchDetailFetch(items)
        batch = BatchFetchService(
            jobs=jobs,
            items=items,
            artifacts=artifacts,
            detail_fetch=detail,  # type: ignore[arg-type]
            policy=BatchPolicy(max_items=10),
        )
        result = await batch.run(object(), job_id=job_id)  # type: ignore[arg-type]

        assert result.status is JobStatus.COMPLETED
        assert result.recovered_count == 2
        assert result.fetched_count == 1
        assert detail.calls == ["Beta"]
        alpha_checkpoint = await items.get_checkpoint(job_id, alpha.item_id)
        assert alpha_checkpoint is not None
        assert alpha_checkpoint.status == "fetched"
        assert alpha_checkpoint.artifact_dir == artifact_dir
        assert await items.count_by_status(job_id) == {"fetched": 2}

    asyncio.run(scenario())
