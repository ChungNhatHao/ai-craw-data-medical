import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.errors import CrawlerError, ErrorCode
from app.models.discovery import DiscoveredItem
from app.models.disease import PartialDiseaseFields
from app.models.tabs import RawDiseaseTab, RawTabRelatedDetail
from app.parser.chunks import MarkdownChunk
from app.parser.extractor import ContentExtractor
from app.parser.structured import PARSER_VERSION, RuleBasedStructuredClient
from app.plugins.fake import FakeSitePlugin
from app.repositories.attempts import AttemptRepository
from app.repositories.database import Database
from app.repositories.items import ItemRepository
from app.repositories.jobs import JobRepository
from app.services.cleaning import CleaningService
from app.services.parsing import StructuredParsingService
from app.storage.artifacts import ArtifactStore

FIXTURE = Path("tests/fixtures/genre_manuals/disease_content_complex.html")
FIXTURE_HTML = FIXTURE.read_text(encoding="utf-8")


class HallucinatingClient:
    method = "llm"
    model_id = "fake-hallucinating-v1"
    supports_repair = False

    async def parse_chunk(
        self,
        *,
        chunk: MarkdownChunk,
        prompt: str,
    ) -> PartialDiseaseFields:
        del chunk, prompt
        return PartialDiseaseFields(
            name="Invented disease",
            treatment=("Invented treatment",),
        )

    async def repair(
        self,
        *,
        markdown: str,
        prompt: str,
        validation_error: str,
    ) -> PartialDiseaseFields:
        del markdown, prompt, validation_error
        raise AssertionError("Repair must not run when supports_repair is false")


class RepairingClient(HallucinatingClient):
    model_id = "fake-repairing-v1"
    supports_repair = True

    def __init__(self) -> None:
        self.repair_calls = 0

    async def repair(
        self,
        *,
        markdown: str,
        prompt: str,
        validation_error: str,
    ) -> PartialDiseaseFields:
        del markdown, prompt, validation_error
        self.repair_calls += 1
        return PartialDiseaseFields(name="Complex disease")


async def prepare_cleaned(
    settings: Settings,
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
    attempts = AttemptRepository(database)
    artifacts = ArtifactStore(settings.output_root)
    await items.upsert_discovered(str(job.id), [item])
    _, artifact_dir = artifacts.persist_raw(
        job_id=str(job.id),
        plugin="fake",
        item=item,
        html=FIXTURE_HTML,
        screenshot=None,
        confidence=1,
        tabs=(
            RawDiseaseTab(
                key="info",
                label="Info",
                source_url=item.canonical_url,
                html=(
                    '<div class="genrearticle">'
                    '<div class="synonyms">A00 * A01.1</div>'
                    '<div class="intro"></div></div>'
                    '<div class="genrearticle">'
                    '<div class="synonyms">Complex disease * CD</div>'
                    '<div class="intro">'
                    '<p>Source summary for output chunking.</p>'
                    '<table><tr><td>Symptoms</td><td>Example</td></tr></table>'
                    '</div></div>'
                ),
            ),
            RawDiseaseTab(
                key="life_dd_tpd",
                label="Life/DD/TPD",
                source_url=item.canonical_url,
                html=(
                    '<table class="floatThead-table"><tr>'
                    '<th>Classification</th><th>Life</th><th>Code</th>'
                    '</tr></table><table id="conditionTable"><tr>'
                    '<th class="level-0">With '
                    '<a class="genrePopup" href="en_hereditarythoraort.htm">'
                    'Hereditary thoracic aortic disease</a></th>'
                    '<td>D</td><td>I71.9</td></tr></table>'
                ),
                related_details=(
                    RawTabRelatedDetail(
                        label="Hereditary thoracic aortic disease",
                        url=(
                            "https://www.genre-manuals.com/"
                            "en_hereditarythoraort.htm"
                        ),
                        html=(
                            "<article><h1>Hereditary thoracic aortic disease</h1>"
                            "<p>Syndromic (e.g. Marfan syndrome).</p></article>"
                        ),
                    ),
                ),
            ),
        ),
    )
    await items.mark_fetched(str(job.id), item.item_id, artifact_dir)
    await CleaningService(
        plugin=FakeSitePlugin(),
        items=items,
        attempts=attempts,
        artifacts=artifacts,
        extractor=ContentExtractor(minimum_chars=50),
    ).run(job_id=str(job.id), item=item)
    return str(job.id), item, items, attempts, artifacts


def test_parsing_service_persists_schema_and_reuses_checkpoint(
    settings: Settings,
) -> None:
    async def scenario() -> None:
        job_id, item, items, attempts, artifacts = await prepare_cleaned(settings)
        service = StructuredParsingService(
            client=RuleBasedStructuredClient(),
            items=items,
            attempts=attempts,
            artifacts=artifacts,
            language="en",
        )

        first = await service.run(job_id=job_id, item=item)
        resumed = await service.run(job_id=job_id, item=item)

        assert not first.reused_artifacts
        assert resumed.reused_artifacts
        assert first.document == resumed.document
        assert first.document.disease.name == "Complex disease"
        assert tuple(
            value.label for value in first.document.menu_hierarchy
        ) == ("Home", "Medical", "Complex disease")
        assert first.document.disease.summary is None
        assert first.document.disease.causes == ()
        assert first.document.source.language == "en"
        assert str(first.document.source.canonical_url) == str(item.canonical_url)
        assert first.document.parse_metadata.method == "rules"
        assert first.document.parse_metadata.prompt_version == "1.0.0"
        assert first.document.parse_metadata.parser_version == PARSER_VERSION
        assert "missing_field:summary" in first.document.parse_metadata.warnings
        assert [section.order for section in first.document.sections] == list(
            range(1, len(first.document.sections) + 1)
        )

        directory = settings.output_root / first.artifact_dir
        disease_bytes = (directory / "disease.json").read_bytes()
        payload = json.loads(disease_bytes)
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        assert payload["schema_version"] == "1.3"
        assert payload["tabs"][0]["tables"][0]["rows"] == [
            ["Codes", "A00 * A01.1"],
            ["Aliases", "Complex disease * CD"],
            ["Summary", "Source summary for output chunking."],
        ]
        assert payload["tabs"][0]["tables"][1]["rows"] == [
            ["Symptoms", "Example"]
        ]
        life_tab = next(
            tab for tab in payload["tabs"] if tab["key"] == "life_dd_tpd"
        )
        hereditary_row = life_tab["classification_table"]["rows"][0]
        assert hereditary_row["classification"] == (
            "With Hereditary thoracic aortic disease"
        )
        assert hereditary_row["related_details"][0]["label"] == (
            "Hereditary thoracic aortic disease"
        )
        assert "Marfan syndrome" in (
            hereditary_row["related_details"][0]["plain_text"]
        )
        assert life_tab["related_details"][0]["label"] == (
            "Hereditary thoracic aortic disease"
        )
        assert manifest["state"] == "parsed"
        assert manifest["schema_hash"] == first.schema_hash
        assert manifest["parser_version"] == PARSER_VERSION
        assert manifest["prompt_version"] == "1.0.0"
        assert (
            hashlib.sha256(disease_bytes).hexdigest()
            == manifest["artifacts"]["disease_json"]["sha256"]
        )
        assert not list(directory.glob(".*.tmp"))
        checkpoint = await items.get_checkpoint(job_id, item.item_id)
        assert checkpoint is not None
        assert checkpoint.status == "parsed"
        history = await attempts.list_for_item(job_id, item.item_id)
        assert len([attempt for attempt in history if attempt.stage == "parse_structured"]) == 1

    asyncio.run(scenario())


def test_hallucinated_output_does_not_overwrite_valid_document(
    settings: Settings,
) -> None:
    async def scenario() -> None:
        job_id, item, items, attempts, artifacts = await prepare_cleaned(settings)
        valid_service = StructuredParsingService(
            client=RuleBasedStructuredClient(),
            items=items,
            attempts=attempts,
            artifacts=artifacts,
            language="en",
        )
        valid = await valid_service.run(job_id=job_id, item=item)
        directory = settings.output_root / valid.artifact_dir
        before = (directory / "disease.json").read_bytes()

        invalid_service = StructuredParsingService(
            client=HallucinatingClient(),
            items=items,
            attempts=attempts,
            artifacts=artifacts,
            language="en",
        )
        with pytest.raises(CrawlerError) as captured:
            await invalid_service.run(job_id=job_id, item=item)

        assert captured.value.code is ErrorCode.LLM_OUTPUT_INVALID
        assert (directory / "disease.json").read_bytes() == before
        checkpoint = await items.get_checkpoint(job_id, item.item_id)
        assert checkpoint is not None
        assert checkpoint.status == "retryable_failed"
        history = await attempts.list_for_item(job_id, item.item_id)
        assert history[-1].result == "failure"
        assert history[-1].error_code == ErrorCode.LLM_OUTPUT_INVALID.value

    asyncio.run(scenario())


def test_invalid_model_output_is_repaired_at_most_once(
    settings: Settings,
) -> None:
    async def scenario() -> None:
        job_id, item, items, attempts, artifacts = await prepare_cleaned(settings)
        client = RepairingClient()
        service = StructuredParsingService(
            client=client,
            items=items,
            attempts=attempts,
            artifacts=artifacts,
            language="en",
        )

        result = await service.run(job_id=job_id, item=item)

        assert client.repair_calls == 1
        assert result.document.disease.name == "Complex disease"
        assert "validation_repair_applied" in result.document.parse_metadata.warnings
        history = await attempts.list_for_item(job_id, item.item_id)
        assert len([attempt for attempt in history if attempt.stage == "parse_structured"]) == 1

    asyncio.run(scenario())
