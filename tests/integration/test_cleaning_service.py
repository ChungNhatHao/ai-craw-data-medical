import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.errors import CrawlerError, ErrorCode
from app.models.discovery import DiscoveredItem
from app.models.tabs import RawDiseaseTab, RawTabRelatedDetail
from app.parser.extractor import ContentExtractor
from app.plugins.fake import FakeSitePlugin
from app.repositories.attempts import AttemptRepository
from app.repositories.database import Database
from app.repositories.items import ItemRepository
from app.repositories.jobs import JobRepository
from app.services.cleaning import CLEANER_VERSION, CleaningService
from app.storage.artifacts import ArtifactStore

FIXTURE = Path("tests/fixtures/genre_manuals/disease_content_complex.html")
FIXTURE_HTML = FIXTURE.read_text(encoding="utf-8")


async def prepare(
    settings: Settings,
    *,
    raw_html: str,
    tabs: tuple[RawDiseaseTab, ...] = (),
) -> tuple[
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
    artifacts = ArtifactStore(settings.output_root)
    _, artifact_dir = artifacts.persist_raw(
        job_id=str(job.id),
        plugin="fake",
        item=item,
        html=raw_html,
        screenshot=None,
        confidence=1,
        tabs=tabs,
    )
    await items.mark_fetched(str(job.id), item.item_id, artifact_dir)
    return (
        str(job.id),
        item,
        items,
        AttemptRepository(database),
        artifacts,
    )


def test_cleaning_service_persists_hash_and_reuses_checkpoint(
    settings: Settings,
) -> None:
    async def scenario() -> None:
        job_id, item, items, attempts, artifacts = await prepare(
            settings,
            raw_html=FIXTURE_HTML,
        )
        service = CleaningService(
            plugin=FakeSitePlugin(),
            items=items,
            attempts=attempts,
            artifacts=artifacts,
            extractor=ContentExtractor(minimum_chars=50),
        )

        first = await service.run(job_id=job_id, item=item)
        resumed = await service.run(job_id=job_id, item=item)

        assert not first.reused_artifacts
        assert resumed.reused_artifacts
        assert resumed.content_hash == first.content_hash
        directory = settings.output_root / first.artifact_dir
        markdown = (directory / "markdown.md").read_bytes()
        manifest = json.loads(
            (directory / "manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["state"] == "cleaned"
        assert manifest["cleaner_version"] == CLEANER_VERSION
        assert hashlib.sha256(markdown).hexdigest() == first.content_hash
        assert "content_html" in manifest["artifacts"]
        assert "markdown" in manifest["artifacts"]
        assert not list(directory.glob(".*.tmp"))
        checkpoint = await items.get_checkpoint(job_id, item.item_id)
        assert checkpoint is not None
        assert checkpoint.status == "cleaned"
        assert checkpoint.content_hash == first.content_hash
        history = await attempts.list_for_item(job_id, item.item_id)
        assert len([attempt for attempt in history if attempt.stage == "clean_markdown"]) == 1

    asyncio.run(scenario())


def test_empty_content_is_not_marked_cleaned(settings: Settings) -> None:
    async def scenario() -> None:
        job_id, item, items, attempts, artifacts = await prepare(
            settings,
            raw_html="<html><body><div>menu only</div></body></html>",
        )
        service = CleaningService(
            plugin=FakeSitePlugin(),
            items=items,
            attempts=attempts,
            artifacts=artifacts,
            extractor=ContentExtractor(minimum_chars=50),
        )

        with pytest.raises(CrawlerError) as captured:
            await service.run(job_id=job_id, item=item)

        assert captured.value.code is ErrorCode.CONTENT_EMPTY
        checkpoint = await items.get_checkpoint(job_id, item.item_id)
        assert checkpoint is not None
        assert checkpoint.status == "retryable_failed"
        directory, _ = artifacts.item_directory(job_id, item)
        assert not (directory / "markdown.md").exists()
        history = await attempts.list_for_item(job_id, item.item_id)
        assert history[-1].result == "failure"
        assert history[-1].error_code == ErrorCode.CONTENT_EMPTY.value

    asyncio.run(scenario())


def test_cleaning_preserves_all_tab_text_and_tables(
    settings: Settings,
) -> None:
    async def scenario() -> None:
        source = "https://example.test/diseases/alpha"
        raw_tabs = (
            RawDiseaseTab(
                key="info",
                label="Info",
                source_url=source,
                html="<div><p>Clinical information.</p></div>",
            ),
            RawDiseaseTab(
                key="life_dd_tpd",
                label="Life/DD/TPD",
                source_url=f"{source}/tabs.ajax",
                html=(
                    '<table class="floatThead-table">'
                    "<tr><th>Classification</th><th>Life</th></tr></table>"
                    '<table id="conditionTable">'
                    '<tr><th class="level-0">All cases</th><td></td></tr>'
                    '<tr><th class="level" style="padding-left: 25px">'
                    "Confirmed case</th><td>D</td></tr></table>"
                ),
                related_details=(
                    RawTabRelatedDetail(
                        label="Life",
                        url=f"{source}/life.htm",
                        html=(
                            "<article><h1>Life Insurance</h1>"
                            "<p>Read-only underwriting guidance.</p></article>"
                        ),
                    ),
                ),
            ),
            RawDiseaseTab(
                key="ip",
                label="IP",
                source_url=f"{source}/tabs.ajax",
                html="<p>IP classification D2/52.</p>",
            ),
            RawDiseaseTab(
                key="health",
                label="Health",
                source_url=f"{source}/tabs.ajax",
                available=False,
                warning="tab_link_not_found",
            ),
        )
        job_id, item, items, attempts, artifacts = await prepare(
            settings,
            raw_html=FIXTURE_HTML,
            tabs=raw_tabs,
        )
        await CleaningService(
            plugin=FakeSitePlugin(),
            items=items,
            attempts=attempts,
            artifacts=artifacts,
            extractor=ContentExtractor(minimum_chars=50),
        ).run(job_id=job_id, item=item)

        tabs = artifacts.read_tabs(
            job_id,
            item,
            cleaner_version=CLEANER_VERSION,
        )
        assert [tab.key for tab in tabs] == [
            "info",
            "life_dd_tpd",
            "ip",
            "health",
        ]
        assert tabs[1].tables[1].rows[1] == ("Confirmed case", "D")
        classification = tabs[1].classification_table
        assert classification is not None
        assert classification.headers == ("Classification", "Life")
        assert classification.rows[0].is_group
        assert classification.rows[1].classification_path == (
            "All cases",
            "Confirmed case",
        )
        assert classification.rows[1].parent_classification == "All cases"
        assert (
            classification.rows[1].parent_classification_id
            == classification.rows[0].classification_id
        )
        assert classification.rows[1].ratings == {"Life": "D"}
        assert classification.tree[0].children[0].classification == (
            "Confirmed case"
        )
        assert tabs[1].related_details[0].label == "Life"
        assert "underwriting guidance" in (
            tabs[1].related_details[0].plain_text
        )
        assert "IP classification" in tabs[2].plain_text
        assert not tabs[3].available
        assert tabs[3].warnings == ("tab_link_not_found",)
        directory, _ = artifacts.item_directory(job_id, item)
        manifest = json.loads(
            (directory / "manifest.json").read_text(encoding="utf-8")
        )
        assert "tabs_raw" in manifest["artifacts"]
        assert "tabs" in manifest["artifacts"]

    asyncio.run(scenario())
