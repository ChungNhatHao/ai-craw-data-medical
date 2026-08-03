import asyncio
import json
from typing import Any

from app.agents.disease_extraction_agent import DiseaseExtractionAgent
from app.core.config import Settings
from app.models.agentic import DiseaseDraft, EvidenceValue
from app.models.disease import ParsingPolicy
from app.parser.extractor import ContentExtractor
from app.plugins.fake import FakeSitePlugin
from app.services.agentic_parsing import (
    AGENTIC_PARSER_VERSION,
    AgenticParsingService,
)
from tests.integration.test_parsing_service import prepare_cleaned


class FakeExtractionClient:
    async def generate_structured(
        self,
        *,
        agent_name: str,
        prompt: str,
        payload: dict[str, object],
        response_model: Any,
    ) -> DiseaseDraft:
        del prompt, response_model
        assert agent_name == "disease_extraction"
        assert "clean_html" not in payload
        assert "raw_html" not in payload
        return DiseaseDraft(
            name=EvidenceValue(
                value="Complex disease",
                source_quote="Complex disease",
                source_section="Title",
            ),
            symptoms=(
                EvidenceValue(
                    value="First symptom",
                    source_quote="First symptom",
                    source_section="Symptoms",
                ),
            ),
        )


class UngroundedExtractionClient:
    def __init__(self) -> None:
        self.call_count = 0

    async def generate_structured(
        self,
        *,
        agent_name: str,
        prompt: str,
        payload: dict[str, object],
        response_model: Any,
    ) -> DiseaseDraft:
        del prompt, payload, response_model
        assert agent_name == "disease_extraction"
        self.call_count += 1
        return DiseaseDraft(
            name=EvidenceValue(
                value="Complex disease",
                source_quote="Complex disease",
            ),
            symptoms=(
                EvidenceValue(
                    value="Invented symptom",
                    source_quote="Invented symptom",
                ),
            ),
        )


def test_agentic_parsing_uses_beautifulsoup_content_and_persists_audit(
    settings: Settings,
) -> None:
    async def scenario() -> None:
        job_id, item, items, attempts, artifacts = await prepare_cleaned(settings)
        service = AgenticParsingService(
            extraction_agent=DiseaseExtractionAgent(
                FakeExtractionClient(),  # type: ignore[arg-type]
            ),
            normalization_agent=None,
            plugin=FakeSitePlugin(),
            items=items,
            attempts=attempts,
            artifacts=artifacts,
            extractor=ContentExtractor(minimum_chars=50),
            language="en",
            model_version="fake-gemini",
            policy=ParsingPolicy(
                timeout_seconds=settings.parse_timeout_seconds,
                max_model_calls=settings.parse_max_model_calls,
                max_input_chars=settings.parse_max_input_chars,
            ),
        )

        first = await service.run(job_id=job_id, item=item)
        resumed = await service.run(job_id=job_id, item=item)

        assert first.document.disease.name == "Complex disease"
        assert first.document.disease.symptoms == ("First symptom",)
        assert tuple(
            value.label for value in first.document.menu_hierarchy
        ) == ("Home", "Medical", "Complex disease")
        assert first.document.menu_hierarchy[-1].distance_from_disease == 0
        assert first.document.parse_metadata.method == "llm"
        assert first.document.parse_metadata.parser_version == (
            AGENTIC_PARSER_VERSION
        )
        assert resumed.reused_artifacts
        directory = settings.output_root / first.artifact_dir
        assert (directory / "disease-draft.json").is_file()
        assert (directory / "normalization.json").is_file()
        manifest = json.loads(
            (directory / "manifest.json").read_text(encoding="utf-8")
        )
        assert "disease_draft" in manifest["artifacts"]
        assert "normalization" in manifest["artifacts"]
        assert "disease_json" in manifest["artifacts"]

    asyncio.run(scenario())


def test_agentic_parsing_falls_back_when_both_grounding_attempts_fail(
    settings: Settings,
) -> None:
    async def scenario() -> None:
        job_id, item, items, attempts, artifacts = await prepare_cleaned(
            settings
        )
        client = UngroundedExtractionClient()
        service = AgenticParsingService(
            extraction_agent=DiseaseExtractionAgent(
                client,  # type: ignore[arg-type]
            ),
            normalization_agent=None,
            plugin=FakeSitePlugin(),
            items=items,
            attempts=attempts,
            artifacts=artifacts,
            extractor=ContentExtractor(minimum_chars=50),
            language="en",
            model_version="fake-gemini",
            policy=ParsingPolicy(
                timeout_seconds=settings.parse_timeout_seconds,
                max_model_calls=settings.parse_max_model_calls,
                max_input_chars=settings.parse_max_input_chars,
            ),
        )

        result = await service.run(job_id=job_id, item=item)

        assert client.call_count == 2
        assert result.document.disease.name == "Complex disease"
        assert (
            "agentic_extraction_fallback:contract_or_grounding"
            in result.document.parse_metadata.warnings
        )
        assert "missing_field:symptoms" in (
            result.document.parse_metadata.warnings
        )
        checkpoint = await items.get_checkpoint(job_id, item.item_id)
        assert checkpoint is not None
        assert checkpoint.status == "parsed"
        history = await attempts.list_for_item(job_id, item.item_id)
        parse_attempt = next(
            attempt
            for attempt in history
            if attempt.stage == "parse_agentic"
        )
        assert parse_attempt.result == "success"

    asyncio.run(scenario())
