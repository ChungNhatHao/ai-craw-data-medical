import asyncio
from typing import Literal, cast

from pydantic import ValidationError

from app.core.errors import CrawlerError, ErrorCode
from app.models.discovery import DiscoveredItem
from app.models.disease import (
    DiseaseDocument,
    DiseaseSource,
    ParsedArtifactResult,
    ParseMetadata,
    ParsingPolicy,
)
from app.parser.chunks import chunk_by_heading
from app.parser.structured import (
    PARSER_VERSION,
    PROMPT_VERSION,
    StructuredModelClient,
    disease_schema_hash,
    load_parser_prompt,
    merge_partial_fields,
    missing_field_warnings,
    validate_grounding,
)
from app.repositories.attempts import AttemptRepository
from app.repositories.items import ItemRepository
from app.services.cleaning import CLEANER_VERSION
from app.storage.artifacts import ArtifactStore

ParseMethod = Literal["rules", "llm", "rules+llm"]


class StructuredParsingService:
    def __init__(
        self,
        *,
        client: StructuredModelClient,
        items: ItemRepository,
        attempts: AttemptRepository,
        artifacts: ArtifactStore,
        language: str,
        policy: ParsingPolicy | None = None,
    ) -> None:
        self.client = client
        self.items = items
        self.attempts = attempts
        self.artifacts = artifacts
        self.language = language
        self.policy = policy or ParsingPolicy()

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
            parser_version=PARSER_VERSION,
            prompt_version=PROMPT_VERSION,
            schema_hash=schema_hash,
            model_version=self.client.model_id,
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
            if (
                baseline is not None
                and baseline.job_id == current_manifest.baseline_job_id
            ):
                reused = self.artifacts.reuse_valid_document(
                    job_id=job_id,
                    item=item,
                    baseline_job_id=baseline.job_id,
                    baseline_item=baseline.item,
                    cleaner_version=CLEANER_VERSION,
                    parser_version=PARSER_VERSION,
                    prompt_version=PROMPT_VERSION,
                    schema_hash=schema_hash,
                    model_version=self.client.model_id,
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
            "parse_structured",
        )
        attempt_id = await self.attempts.start(
            job_id,
            item.item_id,
            attempt_no,
            "parse_structured",
        )
        await self.items.mark_parsing(job_id, item.item_id)
        try:
            manifest, markdown = self.artifacts.read_markdown(
                job_id,
                item,
                cleaner_version=CLEANER_VERSION,
            )
            if len(markdown) > self.policy.max_input_chars:
                raise CrawlerError(
                    ErrorCode.LLM_OUTPUT_INVALID,
                    "Markdown exceeds the configured parser input budget",
                )
            chunks = chunk_by_heading(markdown)
            if not chunks:
                raise CrawlerError(
                    ErrorCode.CONTENT_EMPTY,
                    "Markdown has no parseable content",
                )
            if len(chunks) > self.policy.max_model_calls:
                raise CrawlerError(
                    ErrorCode.LLM_OUTPUT_INVALID,
                    "Heading chunks exceed the configured model-call budget",
                )
            prompt = load_parser_prompt()
            repair_applied = False
            try:
                async with asyncio.timeout(self.policy.timeout_seconds):
                    partials = tuple(
                        [
                            await self.client.parse_chunk(
                                chunk=chunk,
                                prompt=prompt,
                            )
                            for chunk in chunks
                        ]
                    )
                    try:
                        fields = merge_partial_fields(partials)
                        validate_grounding(fields, markdown)
                    except CrawlerError as initial:
                        if (
                            initial.code is not ErrorCode.LLM_OUTPUT_INVALID
                            or not self.client.supports_repair
                            or len(chunks) >= self.policy.max_model_calls
                        ):
                            raise
                        repaired = await self.client.repair(
                            markdown=markdown,
                            prompt=prompt,
                            validation_error=str(initial),
                        )
                        fields = merge_partial_fields((repaired,))
                        validate_grounding(fields, markdown)
                        repair_applied = True
            except TimeoutError as exc:
                raise CrawlerError(
                    ErrorCode.PARSE_TIMEOUT,
                    "Structured parsing exceeded its timeout",
                ) from exc

            if manifest.content_hash is None:
                raise CrawlerError(
                    ErrorCode.CONTENT_INVALID,
                    "Clean manifest is missing its content hash",
                )
            method = cast(ParseMethod, self.client.method)
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
                    method=method,
                    model=self.client.model_id,
                    prompt_version=PROMPT_VERSION,
                    parser_version=PARSER_VERSION,
                    confidence=None,
                    warnings=tuple(
                        (
                            *missing_field_warnings(fields),
                            *(("validation_repair_applied",) if repair_applied else ()),
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
                parser_version=PARSER_VERSION,
                prompt_version=PROMPT_VERSION,
                model_version=self.client.model_id,
            )
            await self.items.mark_parsed(job_id, item.item_id, artifact_dir)
        except CrawlerError as exc:
            await self._finish_failure(
                attempt_id,
                job_id,
                item.item_id,
                exc,
            )
            raise
        except ValidationError as exc:
            invalid = CrawlerError(
                ErrorCode.LLM_OUTPUT_INVALID,
                "Structured model output failed schema validation",
            )
            await self._finish_failure(
                attempt_id,
                job_id,
                item.item_id,
                invalid,
            )
            raise invalid from exc
        except Exception as exc:
            unexpected = CrawlerError(
                ErrorCode.UNEXPECTED,
                "Unexpected failure while parsing structured disease data",
            )
            await self._finish_failure(
                attempt_id,
                job_id,
                item.item_id,
                unexpected,
            )
            raise unexpected from exc
        else:
            await self.attempts.finish(attempt_id, result="success")
            return ParsedArtifactResult(
                job_id=job_id,
                item_id=item.item_id,
                artifact_dir=artifact_dir,
                document=document,
                schema_hash=schema_hash,
            )

    async def _finish_failure(
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
        await self.items.mark_parse_failed(
            job_id,
            item_id,
            error.code.value,
        )
