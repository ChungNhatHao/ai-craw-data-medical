import asyncio
import json
from pathlib import Path

from bs4 import BeautifulSoup

from app.core.config import get_settings
from app.parser.extractor import ContentExtractor
from app.plugins.genre_manuals.live_support import find_latest_artifact_job
from app.plugins.genre_manuals.plugin import GenreManualsPlugin
from app.repositories.attempts import AttemptRepository
from app.repositories.database import Database
from app.repositories.items import ItemRepository
from app.services.cleaning import CleaningService
from app.storage.artifacts import ArtifactStore

FORBIDDEN_MARKERS = (
    "logout",
    "disease menu must be removed",
    "footer must be removed",
)


def _read_clean_artifacts(directory: Path) -> tuple[str, str]:
    return (
        (directory / "content.html").read_text(encoding="utf-8"),
        (directory / "markdown.md").read_text(encoding="utf-8"),
    )


async def validate_day7() -> dict[str, object]:
    settings = get_settings()
    job_id = find_latest_artifact_job(
        settings.output_root,
        minimum_items=2,
    )
    database = Database(settings.database_path, settings.migrations_path)
    await database.initialize()
    items = ItemRepository(database)
    candidates = await items.list_by_status(
        job_id,
        ("fetched", "cleaning", "cleaned"),
    )
    artifacts = ArtifactStore(settings.output_root)
    candidates = [
        item
        for item in candidates
        if artifacts.load_valid_raw(job_id, item) is not None
    ]
    if len(candidates) < 2:
        raise RuntimeError("Two valid Day 6 raw items are required")

    plugin = GenreManualsPlugin(
        base_url=str(settings.genre_manuals_base_url),
        detail_confidence_threshold=settings.disease_detail_confidence_threshold,
    )
    attempts = AttemptRepository(database)
    service = CleaningService(
        plugin=plugin,
        items=items,
        attempts=attempts,
        artifacts=artifacts,
        extractor=ContentExtractor(minimum_chars=50),
    )
    results = [
        await service.run(job_id=job_id, item=item)
        for item in candidates[:2]
    ]
    resumed = await service.run(job_id=job_id, item=candidates[0])

    item_summaries: list[dict[str, object]] = []
    for item, result in zip(candidates[:2], results, strict=True):
        directory, _ = artifacts.item_directory(job_id, item)
        content_html, markdown = _read_clean_artifacts(directory)
        soup = BeautifulSoup(content_html, "lxml")
        forbidden_tags = sum(
            len(soup.select(selector))
            for selector in ("script", "nav", "footer", "form", "#sidemenutree")
        )
        forbidden_text = sum(
            marker in markdown.lower() for marker in FORBIDDEN_MARKERS
        )
        history = await attempts.list_for_item(job_id, item.item_id)
        item_summaries.append(
            {
                "item_id_prefix": item.item_id[:12],
                "markdown_chars": len(markdown),
                "content_hash": result.content_hash,
                "warnings": result.warnings,
                "forbidden_tags": forbidden_tags,
                "forbidden_text_markers": forbidden_text,
                "clean_attempt_records": len(
                    [
                        attempt
                        for attempt in history
                        if attempt.stage == "clean_markdown"
                    ]
                ),
            }
        )

    return {
        "job_id": job_id,
        "items_cleaned": len(results),
        "restart_reused_artifact": resumed.reused_artifacts,
        "restart_hash_stable": resumed.content_hash == results[0].content_hash,
        "database_status_counts": await items.count_by_status(job_id),
        "items": item_summaries,
        "artifact_root": f"jobs/{job_id}/items",
    }


def main() -> None:
    print(json.dumps(asyncio.run(validate_day7()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
