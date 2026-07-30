import asyncio
from pathlib import Path

from app.core.config import Settings
from app.models.discovery import DiscoveredItem
from app.models.disease import PartialDiseaseFields
from app.parser.chunks import MarkdownChunk
from app.parser.extractor import ContentExtractor
from app.parser.structured import RuleBasedStructuredClient
from app.plugins.fake import FakeSitePlugin
from app.repositories.attempts import AttemptRepository
from app.repositories.database import Database
from app.repositories.items import ItemRepository
from app.repositories.jobs import JobRepository
from app.services.cleaning import CleaningService
from app.services.parsing import StructuredParsingService
from app.storage.artifacts import ArtifactStore

FIXTURE_HTML = Path(
    "tests/fixtures/genre_manuals/disease_content_complex.html"
).read_text(encoding="utf-8")


class CountingRuleClient(RuleBasedStructuredClient):
    def __init__(self) -> None:
        self.calls = 0

    async def parse_chunk(
        self,
        *,
        chunk: MarkdownChunk,
        prompt: str,
    ) -> PartialDiseaseFields:
        self.calls += 1
        return await super().parse_chunk(chunk=chunk, prompt=prompt)


def test_second_identical_job_reuses_structured_document(
    settings: Settings,
) -> None:
    async def scenario() -> None:
        settings.ensure_directories()
        database = Database(settings.database_path, settings.migrations_path)
        await database.initialize()
        jobs = JobRepository(database)
        items = ItemRepository(database)
        attempts = AttemptRepository(database)
        artifacts = ArtifactStore(settings.output_root)
        plugin = FakeSitePlugin()
        item = (await plugin.discover_demo_items())[0]

        async def run_job(
            client: CountingRuleClient,
        ) -> tuple[str, DiscoveredItem, bool]:
            job = await jobs.create(plugin.name)
            job_id = str(job.id)
            await items.upsert_discovered(job_id, [item])
            _, artifact_dir = artifacts.persist_raw(
                job_id=job_id,
                plugin=plugin.name,
                item=item,
                html=FIXTURE_HTML,
                screenshot=None,
                confidence=1,
            )
            await items.mark_fetched(job_id, item.item_id, artifact_dir)
            await CleaningService(
                plugin=plugin,
                items=items,
                attempts=attempts,
                artifacts=artifacts,
                extractor=ContentExtractor(minimum_chars=50),
            ).run(job_id=job_id, item=item)
            parsed = await StructuredParsingService(
                client=client,
                items=items,
                attempts=attempts,
                artifacts=artifacts,
                language="en",
            ).run(job_id=job_id, item=item)
            return job_id, item, parsed.reused_artifacts

        first_client = CountingRuleClient()
        first_job, _, first_reused = await run_job(first_client)
        second_client = CountingRuleClient()
        second_job, _, second_reused = await run_job(second_client)

        assert not first_reused
        assert first_client.calls > 0
        assert second_reused
        assert second_client.calls == 0
        checkpoint = await items.get_checkpoint(second_job, item.item_id)
        assert checkpoint is not None
        assert checkpoint.status == "parsed"
        assert checkpoint.change_status == "unchanged"
        assert checkpoint.baseline_job_id == first_job
        assert checkpoint.snapshot_hash == checkpoint.previous_snapshot_hash
        manifest = artifacts.load_item_manifest(second_job, item)
        assert manifest is not None
        assert "incremental_unchanged_reused" in manifest.warnings

    asyncio.run(scenario())
