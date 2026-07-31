import asyncio
from typing import cast

from pydantic import ValidationError

from app.agents.disease_extraction_agent import DiseaseExtractionAgent
from app.agents.normalization_agent import NormalizationAgent
from app.core.errors import CrawlerError, ErrorCode
from app.models.agentic import (
    AgentNormalizationInput,
    CleanContent,
    DiseaseDraft,
    DiseaseFieldName,
    EvidenceValue,
    NormalizationResult,
)
from app.models.discovery import DiscoveredItem
from app.models.disease import (
    DiseaseDocument,
    DiseaseFields,
    DiseaseSource,
    ParsedArtifactResult,
    ParseMetadata,
    ParsingPolicy,
)
from app.parser.chunks import chunk_by_heading
from app.parser.extractor import ContentExtractor
from app.parser.markdown import MarkdownConverter
from app.parser.structured import (
    disease_schema_hash,
    extract_deterministic_fields,
    missing_field_warnings,
)
from app.plugins.base import SitePlugin
from app.repositories.attempts import AttemptRepository
from app.repositories.items import ItemRepository
from app.services.cleaning import CLEANER_VERSION
from app.storage.artifacts import ArtifactStore

AGENTIC_PARSER_VERSION = "agentic-1.2.0"
AGENTIC_PROMPT_VERSION = "agentic-1.1.0"


class AgenticParsingService:
    """Create grounded disease JSON from BeautifulSoup-cleaned content."""

    def __init__(
        self,
        *,
        extraction_agent: DiseaseExtractionAgent,
        normalization_agent: NormalizationAgent | None,
        plugin: SitePlugin,
        items: ItemRepository,
        attempts: AttemptRepository,
        artifacts: ArtifactStore,
        extractor: ContentExtractor,
        language: str,
        model_version: str,
        policy: ParsingPolicy,
    ) -> None:
        self.extraction_agent = extraction_agent
        self.normalization_agent = normalization_agent
        self.plugin = plugin
        self.items = items
        self.attempts = attempts
        self.artifacts = artifacts
        self.extractor = extractor
        self.language = language
        self.model_version = model_version
        self.policy = policy

    async def run(
        self,
        *,
        job_id: str,
        item: DiscoveredItem,
    ) -> ParsedArtifactResult:
        schema_hash = disease_schema_hash()
        recovered = self.artifacts.load_valid_document(
            job_id,
            item,
            cleaner_version=CLEANER_VERSION,
            parser_version=AGENTIC_PARSER_VERSION,
            prompt_version=AGENTIC_PROMPT_VERSION,
            schema_hash=schema_hash,
            model_version=self.model_version,
        )
        if recovered is not None:
            _, document, artifact_dir = recovered
            await self.items.mark_parsed(job_id, item.item_id, artifact_dir)
            return ParsedArtifactResult(
                job_id=job_id,
                item_id=item.item_id,
                artifact_dir=artifact_dir,
                document=document,
                schema_hash=schema_hash,
                reused_artifacts=True,
            )

        current_manifest = self.artifacts.load_item_manifest(job_id, item)
        if (
            current_manifest is not None
            and current_manifest.change_status == "unchanged"
            and current_manifest.baseline_job_id
        ):
            baseline = await self.items.find_incremental_baseline(
                job_id=job_id,
                item_id=item.item_id,
                plugin=current_manifest.plugin,
            )
            if baseline is not None and baseline.job_id == current_manifest.baseline_job_id:
                reused = self.artifacts.reuse_valid_document(
                    job_id=job_id,
                    item=item,
                    baseline_job_id=baseline.job_id,
                    baseline_item=baseline.item,
                    cleaner_version=CLEANER_VERSION,
                    parser_version=AGENTIC_PARSER_VERSION,
                    prompt_version=AGENTIC_PROMPT_VERSION,
                    schema_hash=schema_hash,
                    model_version=self.model_version,
                )
                if reused is not None:
                    _, document, artifact_dir = reused
                    await self.items.mark_parsed(
                        job_id,
                        item.item_id,
                        artifact_dir,
                    )
                    return ParsedArtifactResult(
                        job_id=job_id,
                        item_id=item.item_id,
                        artifact_dir=artifact_dir,
                        document=document,
                        schema_hash=schema_hash,
                        reused_artifacts=True,
                    )

        attempt_no = await self.attempts.next_attempt_no(
            job_id,
            item.item_id,
            "parse_agentic",
        )
        attempt_id = await self.attempts.start(
            job_id,
            item.item_id,
            attempt_no,
            "parse_agentic",
        )
        await self.items.mark_parsing(job_id, item.item_id)
        try:
            async with asyncio.timeout(self.policy.timeout_seconds):
                manifest, stored_markdown = self.artifacts.read_markdown(
                    job_id,
                    item,
                    cleaner_version=CLEANER_VERSION,
                )
                if len(stored_markdown) > self.policy.max_input_chars:
                    raise CrawlerError(
                        ErrorCode.LLM_OUTPUT_INVALID,
                        "Clean Markdown exceeds the Gemini input budget",
                    )
                extracted = self.extractor.extract(
                    self.artifacts.read_raw_html(job_id, item),
                    root_selectors=self.plugin.content_root_selectors(),
                    title_selectors=self.plugin.content_title_selectors(),
                )
                rebuilt_markdown, _ = MarkdownConverter(self.plugin.canonicalize_url).convert(
                    extracted.html,
                    base_url=str(item.canonical_url),
                )
                if rebuilt_markdown != stored_markdown:
                    raise CrawlerError(
                        ErrorCode.CONTENT_INVALID,
                        "BeautifulSoup clean content differs from stored Markdown",
                    )
                if manifest.content_hash is None:
                    raise CrawlerError(
                        ErrorCode.CONTENT_INVALID,
                        "Clean manifest is missing content hash",
                    )
                chunks = chunk_by_heading(stored_markdown)
                if not chunks:
                    raise CrawlerError(
                        ErrorCode.CONTENT_EMPTY,
                        "Clean Markdown has no parseable content",
                    )
                content = CleanContent(
                    source_url=item.canonical_url,
                    title=item.title_hint,
                    headings=tuple(chunk.heading for chunk in chunks),
                    clean_html=extracted.html,
                    markdown=stored_markdown,
                    plain_text=extracted.plain_text,
                    removed_node_count=extracted.removed_nodes,
                    content_hash=manifest.content_hash,
                )
                draft = await self.extraction_agent.extract(content)
                self.artifacts.persist_auxiliary_json(
                    job_id=job_id,
                    item=item,
                    file_name="disease-draft.json",
                    payload=draft.model_dump(mode="json"),
                )
                draft, backfilled_fields = _backfill_source_explicit_fields(
                    draft,
                    stored_markdown,
                )
                normalized, normalization = await self._normalize(
                    item=item,
                    content=content,
                    draft=draft,
                )
                if backfilled_fields:
                    normalization = normalization.model_copy(
                        update={
                            "changed_fields": tuple(
                                dict.fromkeys(
                                    (
                                        *normalization.changed_fields,
                                        *backfilled_fields,
                                    )
                                )
                            ),
                            "warnings": (
                                *normalization.warnings,
                                *(f"deterministic_backfill:{field}" for field in backfilled_fields),
                            ),
                        }
                    )
                self.artifacts.persist_auxiliary_json(
                    job_id=job_id,
                    item=item,
                    file_name="normalization.json",
                    payload=normalization.model_dump(mode="json"),
                )
                fields = _draft_to_fields(normalized)
                document = DiseaseDocument(
                    document_id=item.item_id,
                    source=DiseaseSource(
                        plugin=manifest.plugin,
                        url=item.source_url,
                        canonical_url=item.canonical_url,
                        retrieved_at=manifest.retrieved_at,
                        content_hash=manifest.content_hash,
                        language=self.language,
                    ),
                    disease=fields,
                    sections=tuple(chunk.as_section() for chunk in chunks),
                    tabs=self.artifacts.read_tabs(
                        job_id,
                        item,
                        cleaner_version=CLEANER_VERSION,
                    ),
                    parse_metadata=ParseMetadata(
                        method="llm",
                        model=self.model_version,
                        prompt_version=AGENTIC_PROMPT_VERSION,
                        parser_version=AGENTIC_PARSER_VERSION,
                        confidence=None,
                        warnings=tuple(
                            (
                                *missing_field_warnings(fields),
                                *normalization.warnings,
                            )
                        ),
                    ),
                )
                _, artifact_dir = self.artifacts.persist_document(
                    job_id=job_id,
                    item=item,
                    document=document,
                    schema_hash=schema_hash,
                    cleaner_version=CLEANER_VERSION,
                    parser_version=AGENTIC_PARSER_VERSION,
                    prompt_version=AGENTIC_PROMPT_VERSION,
                    model_version=self.model_version,
                )
                await self.items.mark_parsed(
                    job_id,
                    item.item_id,
                    artifact_dir,
                )
        except TimeoutError as exc:
            error = CrawlerError(
                ErrorCode.PARSE_TIMEOUT,
                "Gemini disease extraction exceeded its timeout",
            )
            await self._fail(attempt_id, job_id, item.item_id, error)
            raise error from exc
        except CrawlerError as exc:
            await self._fail(attempt_id, job_id, item.item_id, exc)
            raise
        except (ValidationError, ValueError) as exc:
            error = CrawlerError(
                ErrorCode.GROUNDING_FAILED,
                "Agentic disease output failed contract or grounding validation",
            )
            await self._fail(attempt_id, job_id, item.item_id, error)
            raise error from exc
        except Exception as exc:
            error = CrawlerError(
                ErrorCode.UNEXPECTED,
                "Unexpected agentic disease parsing failure",
            )
            await self._fail(attempt_id, job_id, item.item_id, error)
            raise error from exc
        else:
            await self.attempts.finish(attempt_id, result="success")
            return ParsedArtifactResult(
                job_id=job_id,
                item_id=item.item_id,
                artifact_dir=artifact_dir,
                document=document,
                schema_hash=schema_hash,
            )

    async def _normalize(
        self,
        *,
        item: DiscoveredItem,
        content: CleanContent,
        draft: DiseaseDraft,
    ) -> tuple[DiseaseDraft, NormalizationResult]:
        deterministic = _deduplicate_draft(draft)
        ambiguous_fields: tuple[DiseaseFieldName, ...] = ()
        if self.normalization_agent is None or not ambiguous_fields:
            return deterministic, NormalizationResult(
                normalized_draft=deterministic,
                warnings=("ai_normalization_not_required",),
            )
        normalization = await self.normalization_agent.normalize(
            AgentNormalizationInput(
                source_url=item.canonical_url,
                content_hash=content.content_hash,
                draft=deterministic,
                ambiguous_fields=ambiguous_fields,
                evidence_text=content.plain_text,
            )
        )
        return normalization.normalized_draft, normalization

    async def _fail(
        self,
        attempt_id: int,
        job_id: str,
        item_id: str,
        error: CrawlerError,
    ) -> None:
        await self.attempts.finish(
            attempt_id,
            result="failure",
            error_code=error.code.value,
            error_message=str(error),
        )
        await self.items.mark_parse_failed(job_id, item_id, error.code.value)


def _draft_to_fields(draft: DiseaseDraft) -> DiseaseFields:
    return DiseaseFields(
        name=draft.name.value,
        aliases=tuple(value.value for value in draft.aliases),
        summary=draft.summary.value if draft.summary else None,
        causes=tuple(value.value for value in draft.causes),
        risk_factors=tuple(value.value for value in draft.risk_factors),
        symptoms=tuple(value.value for value in draft.symptoms),
        diagnosis=tuple(value.value for value in draft.diagnosis),
        treatment=tuple(value.value for value in draft.treatment),
        prevention=tuple(value.value for value in draft.prevention),
        prognosis=draft.prognosis.value if draft.prognosis else None,
        when_to_seek_care=tuple(value.value for value in draft.when_to_seek_care),
    )


def _deduplicate_draft(draft: DiseaseDraft) -> DiseaseDraft:
    updates: dict[str, object] = {}
    for field_name in (
        "aliases",
        "causes",
        "risk_factors",
        "symptoms",
        "diagnosis",
        "treatment",
        "prevention",
        "when_to_seek_care",
    ):
        values = cast(tuple[EvidenceValue, ...], getattr(draft, field_name))
        unique: list[EvidenceValue] = []
        seen: set[str] = set()
        for evidence in values:
            key = " ".join(evidence.value.casefold().split())
            if key in seen:
                continue
            seen.add(key)
            unique.append(evidence)
        updates[field_name] = tuple(unique)
    return draft.model_copy(update=updates)


def _backfill_source_explicit_fields(
    draft: DiseaseDraft,
    markdown: str,
) -> tuple[DiseaseDraft, tuple[DiseaseFieldName, ...]]:
    """Fill model omissions only when deterministic source structure is explicit."""
    deterministic = extract_deterministic_fields(markdown)
    updates: dict[str, object] = {}
    changed: list[DiseaseFieldName] = []
    scalar_fields: tuple[DiseaseFieldName, ...] = ("summary", "prognosis")
    list_fields: tuple[DiseaseFieldName, ...] = (
        "aliases",
        "causes",
        "risk_factors",
        "symptoms",
        "diagnosis",
        "treatment",
        "prevention",
        "when_to_seek_care",
    )

    for field_name in scalar_fields:
        if getattr(draft, field_name) is not None:
            continue
        value = getattr(deterministic, field_name)
        if value is None:
            continue
        updates[field_name] = EvidenceValue(
            value=value,
            source_quote=value,
            source_section="Deterministic source extraction",
        )
        changed.append(field_name)

    for field_name in list_fields:
        if getattr(draft, field_name):
            continue
        values = getattr(deterministic, field_name)
        if not values:
            continue
        updates[field_name] = tuple(
            EvidenceValue(
                value=value,
                source_quote=value,
                source_section="Deterministic source extraction",
            )
            for value in values
        )
        changed.append(field_name)

    if not updates:
        return draft, ()
    return draft.model_copy(update=updates), tuple(changed)
