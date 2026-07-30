import asyncio
import hashlib
import json
from typing import Any

from app.agents.item_graph import build_raw_fetch_graph
from app.core.config import Settings
from app.core.errors import CrawlerError, ErrorCode
from app.models.artifacts import RawFetchPolicy
from app.models.discovery import DiscoveredItem
from app.plugins.fake import FakeSitePlugin
from app.repositories.attempts import AttemptRepository
from app.repositories.database import Database
from app.repositories.items import ItemRepository
from app.repositories.jobs import JobRepository
from app.services.detail_fetch import DetailFetchService
from app.storage.artifacts import ArtifactStore

PNG_FIXTURE = b"\x89PNG\r\n\x1a\nfixture-image"


class DetailPage:
    def __init__(self) -> None:
        self.content_calls = 0
        self.screenshot_calls = 0

    async def content(self) -> str:
        self.content_calls += 1
        return "<html><main><h1>Alpha</h1><p>Detail content.</p></main></html>"

    async def screenshot(self, **kwargs: Any) -> bytes:
        assert kwargs == {
            "type": "png",
            "full_page": True,
            "mask": [],
            "mask_color": "#20252b",
        }
        self.screenshot_calls += 1
        return PNG_FIXTURE


class RetryOncePlugin(FakeSitePlugin):
    def __init__(self) -> None:
        self.navigation_calls = 0

    async def navigate_to_candidate(self, page: Any, candidate: Any) -> None:
        del page, candidate
        self.navigation_calls += 1
        if self.navigation_calls == 1:
            raise CrawlerError(ErrorCode.NETWORK_TIMEOUT, "Navigation timed out")


async def prepare(
    settings: Settings,
) -> tuple[
    Database,
    str,
    DiscoveredItem,
    ItemRepository,
    AttemptRepository,
    ArtifactStore,
]:
    settings.ensure_directories()
    database = Database(settings.database_path, settings.migrations_path)
    await database.initialize()
    job = await JobRepository(database).create("fake")
    item = (await FakeSitePlugin().discover_demo_items())[0]
    items = ItemRepository(database)
    await items.upsert_discovered(str(job.id), [item])
    return (
        database,
        str(job.id),
        item,
        items,
        AttemptRepository(database),
        ArtifactStore(settings.output_root),
    )


def test_item_graph_persists_raw_screenshot_manifest_and_checkpoint(
    settings: Settings,
) -> None:
    async def scenario() -> None:
        _, job_id, item, items, attempts, artifacts = await prepare(settings)
        page = DetailPage()
        service = DetailFetchService(
            plugin=FakeSitePlugin(),
            items=items,
            attempts=attempts,
            artifacts=artifacts,
            policy=RawFetchPolicy(base_delay_seconds=0),
        )
        graph = build_raw_fetch_graph(  # type: ignore[arg-type]
            page=page,
            item=item,
            service=service,
        )

        result = await graph.ainvoke(
            {"job_id": job_id, "item_id": item.item_id, "stage": "discovered"}
        )

        assert result["stage"] == "fetched"
        assert result["attempt_count"] == 1
        directory = settings.output_root / result["artifact_dir"]
        raw = (directory / "raw.html").read_bytes()
        screenshot = (directory / "screenshot.png").read_bytes()
        manifest = json.loads(
            (directory / "manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["state"] == "fetched"
        assert manifest["artifacts"]["raw_html"]["sha256"] == hashlib.sha256(
            raw
        ).hexdigest()
        assert manifest["artifacts"]["screenshot"]["sha256"] == hashlib.sha256(
            screenshot
        ).hexdigest()
        assert not list(directory.glob(".*.tmp"))

        checkpoint = await items.get_checkpoint(job_id, item.item_id)
        assert checkpoint is not None
        assert checkpoint.status == "fetched"
        assert checkpoint.artifact_dir == result["artifact_dir"]
        history = await attempts.list_for_item(job_id, item.item_id)
        assert [attempt.result for attempt in history] == ["success"]
        assert page.content_calls == 1
        assert page.screenshot_calls == 1

    asyncio.run(scenario())


def test_restart_after_raw_write_reuses_valid_artifacts_without_fetch(
    settings: Settings,
) -> None:
    async def scenario() -> None:
        _, job_id, item, items, attempts, artifacts = await prepare(settings)
        page = DetailPage()
        service = DetailFetchService(
            plugin=FakeSitePlugin(),
            items=items,
            attempts=attempts,
            artifacts=artifacts,
            policy=RawFetchPolicy(base_delay_seconds=0),
        )
        first = await service.run(  # type: ignore[arg-type]
            page,
            job_id=job_id,
            item=item,
        )
        await items.mark_fetching(job_id, item.item_id)

        recovered = await service.run(  # type: ignore[arg-type]
            object(),
            job_id=job_id,
            item=item,
        )

        assert not first.reused_artifacts
        assert recovered.reused_artifacts
        assert recovered.artifact_dir == first.artifact_dir
        assert page.content_calls == 1
        assert len(await attempts.list_for_item(job_id, item.item_id)) == 1
        checkpoint = await items.get_checkpoint(job_id, item.item_id)
        assert checkpoint is not None
        assert checkpoint.status == "fetched"

    asyncio.run(scenario())


def test_network_timeout_creates_attempt_history_and_retries(
    settings: Settings,
) -> None:
    async def scenario() -> None:
        _, job_id, item, items, attempts, artifacts = await prepare(settings)
        delays: list[float] = []

        async def record_delay(delay: float) -> None:
            delays.append(delay)

        plugin = RetryOncePlugin()
        service = DetailFetchService(
            plugin=plugin,
            items=items,
            attempts=attempts,
            artifacts=artifacts,
            policy=RawFetchPolicy(
                max_attempts=3,
                base_delay_seconds=0.25,
                max_delay_seconds=1,
            ),
            sleeper=record_delay,
        )

        result = await service.run(  # type: ignore[arg-type]
            DetailPage(),
            job_id=job_id,
            item=item,
        )

        assert result.attempt_count == 2
        assert plugin.navigation_calls == 2
        assert delays == [0.25]
        history = await attempts.list_for_item(job_id, item.item_id)
        assert [attempt.result for attempt in history] == ["failure", "success"]
        assert history[0].error_code == ErrorCode.NETWORK_TIMEOUT.value

    asyncio.run(scenario())
