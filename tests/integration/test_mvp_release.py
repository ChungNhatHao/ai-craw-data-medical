import asyncio
import hashlib
import json
from pathlib import Path

from app.core.config import Settings
from app.core.errors import ErrorCode
from app.core.ids import build_item_id
from app.models.crawl import JobStatus
from app.models.discovery import DiscoveredItem
from app.parser.extractor import ContentExtractor
from app.parser.structured import RuleBasedStructuredClient
from app.plugins.fake import FakeSitePlugin
from app.repositories.attempts import AttemptRepository
from app.repositories.database import Database
from app.repositories.items import ItemRepository
from app.repositories.jobs import JobRepository
from app.services.cleaning import CleaningService
from app.services.parsing import StructuredParsingService
from app.services.reporting import ReportingService
from app.storage.artifacts import ArtifactStore

FIXTURE_HTML = Path(
    "tests/fixtures/genre_manuals/disease_content_complex.html"
).read_text(encoding="utf-8")
PNG = b"\x89PNG\r\n\x1a\nfixture"


def make_item(name: str) -> DiscoveredItem:
    url = f"https://example.test/diseases/{name}"
    return DiscoveredItem(
        item_id=build_item_id("fake", url),
        source_url=url,
        canonical_url=url,
        title_hint=name.title(),
        discovery_page="https://example.test/diseases",
    )


def test_mvp_replay_e2e_exports_report_with_success_and_failure(
    settings: Settings,
) -> None:
    async def scenario() -> None:
        settings.ensure_directories()
        database = Database(settings.database_path, settings.migrations_path)
        await database.initialize()
        jobs = JobRepository(database)
        job = await jobs.create("fake")
        job_id = str(job.id)
        items = ItemRepository(database)
        attempts = AttemptRepository(database)
        artifacts = ArtifactStore(settings.output_root)
        candidates = [make_item(name) for name in ("alpha", "beta", "not-detail")]
        await items.upsert_discovered(job_id, candidates)

        for item in candidates[:2]:
            _, artifact_dir = artifacts.persist_raw(
                job_id=job_id,
                plugin="fake",
                item=item,
                html=FIXTURE_HTML,
                screenshot=PNG,
                confidence=1,
            )
            await items.mark_fetched(job_id, item.item_id, artifact_dir)
            await CleaningService(
                plugin=FakeSitePlugin(),
                items=items,
                attempts=attempts,
                artifacts=artifacts,
                extractor=ContentExtractor(minimum_chars=50),
            ).run(job_id=job_id, item=item)
            await StructuredParsingService(
                client=RuleBasedStructuredClient(),
                items=items,
                attempts=attempts,
                artifacts=artifacts,
                language="en",
            ).run(job_id=job_id, item=item)

        failed = candidates[2]
        await items.mark_fetching(job_id, failed.item_id)
        await items.mark_fetch_failed(
            job_id,
            failed.item_id,
            ErrorCode.PAGE_TYPE_UNKNOWN.value,
        )
        await jobs.update_status(job_id, JobStatus.COMPLETED_WITH_ERRORS.value)

        report = await ReportingService(
            jobs=jobs,
            items=items,
            artifacts=artifacts,
        ).generate(job_id)

        assert report.status is JobStatus.COMPLETED_WITH_ERRORS
        assert report.total_items == 3
        assert report.successful_items == 2
        assert report.failed_items == 1
        assert sum(item.complete_artifact_set for item in report.items) == 2
        failed_report = next(
            item for item in report.items if item.status == "retryable_failed"
        )
        assert failed_report.last_error_code == ErrorCode.PAGE_TYPE_UNKNOWN.value
        report_path = settings.output_root / "jobs" / job_id / "report.json"
        job_path = settings.output_root / "jobs" / job_id / "job.json"
        final = json.loads(job_path.read_text(encoding="utf-8"))
        assert final["successful_items"] == 2
        assert final["failed_items"] == 1
        assert final["report"]["sha256"] == hashlib.sha256(
            report_path.read_bytes()
        ).hexdigest()
        assert report_path.stat().st_mode & 0o777 == 0o600
        assert job_path.stat().st_mode & 0o777 == 0o600
        assert not list((settings.output_root / "jobs" / job_id).rglob("*.tmp"))

    asyncio.run(scenario())

