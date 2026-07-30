import asyncio
import hashlib
import json

from app.core.config import get_settings
from app.models.disease import DiseaseDocument, ParsingPolicy
from app.parser.structured import RuleBasedStructuredClient, validate_grounding
from app.plugins.genre_manuals.live_support import find_latest_artifact_job
from app.repositories.attempts import AttemptRepository
from app.repositories.database import Database
from app.repositories.items import ItemRepository
from app.services.cleaning import CLEANER_VERSION
from app.services.parsing import StructuredParsingService
from app.storage.artifacts import ArtifactStore


async def validate_day8() -> dict[str, object]:
    settings = get_settings()
    job_id = find_latest_artifact_job(
        settings.output_root,
        minimum_items=2,
    )
    database = Database(settings.database_path, settings.migrations_path)
    await database.initialize()
    items = ItemRepository(database)
    attempts = AttemptRepository(database)
    artifacts = ArtifactStore(settings.output_root)
    candidates = await items.list_by_status(
        job_id,
        ("cleaned", "parsed"),
    )
    candidates = [
        item
        for item in candidates
        if artifacts.load_valid_clean(
            job_id,
            item,
            cleaner_version=CLEANER_VERSION,
        )
        is not None
    ]
    if len(candidates) < 2:
        raise RuntimeError("Two valid Day 7 Markdown items are required")

    service = StructuredParsingService(
        client=RuleBasedStructuredClient(),
        items=items,
        attempts=attempts,
        artifacts=artifacts,
        language="en",
        policy=ParsingPolicy(
            timeout_seconds=settings.parse_timeout_seconds,
            max_model_calls=settings.parse_max_model_calls,
            max_input_chars=settings.parse_max_input_chars,
        ),
    )
    results = [
        await service.run(job_id=job_id, item=item)
        for item in candidates[:2]
    ]
    resumed = await service.run(job_id=job_id, item=candidates[0])

    summaries: list[dict[str, object]] = []
    for item, result in zip(candidates[:2], results, strict=True):
        directory, _ = artifacts.item_directory(job_id, item)
        disease_bytes = (directory / "disease.json").read_bytes()
        document = DiseaseDocument.model_validate_json(disease_bytes)
        _, markdown = artifacts.read_markdown(
            job_id,
            item,
            cleaner_version=CLEANER_VERSION,
        )
        validate_grounding(document.disease, markdown)
        manifest = json.loads(
            (directory / "manifest.json").read_text(encoding="utf-8")
        )
        history = await attempts.list_for_item(job_id, item.item_id)
        extracted_fields = {
            field
            for field, value in document.disease
            if value not in (None, (), "")
        }
        summaries.append(
            {
                "item_id_prefix": item.item_id[:12],
                "disease_name": document.disease.name,
                "sections": len(document.sections),
                "extracted_fields": sorted(extracted_fields),
                "warnings": document.parse_metadata.warnings,
                "source_language": document.source.language,
                "source_content_hash_matches": (
                    document.source.content_hash == result.document.source.content_hash
                ),
                "schema_hash": result.schema_hash,
                "disease_json_hash_matches": (
                    hashlib.sha256(disease_bytes).hexdigest()
                    == manifest["artifacts"]["disease_json"]["sha256"]
                ),
                "grounding_guard": "passed",
                "parse_attempt_records": len(
                    [
                        attempt
                        for attempt in history
                        if attempt.stage == "parse_structured"
                    ]
                ),
            }
        )

    return {
        "job_id": job_id,
        "items_parsed": len(results),
        "method": "rules",
        "external_model_calls": 0,
        "restart_reused_artifact": resumed.reused_artifacts,
        "database_status_counts": await items.count_by_status(job_id),
        "items": summaries,
        "artifact_root": f"jobs/{job_id}/items",
    }


def main() -> None:
    print(json.dumps(asyncio.run(validate_day8()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
