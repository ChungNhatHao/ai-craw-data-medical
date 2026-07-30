import asyncio
import json

from app.agents.item_graph import build_raw_fetch_graph
from app.browser.manager import BrowserManager
from app.browser.session import SessionStore
from app.core.config import get_settings
from app.models.artifacts import RawFetchPolicy
from app.plugins.genre_manuals.live_support import load_latest_discovered_items
from app.plugins.genre_manuals.plugin import GenreManualsPlugin
from app.repositories.attempts import AttemptRepository
from app.repositories.database import Database
from app.repositories.items import ItemRepository
from app.repositories.jobs import JobRepository
from app.services.detail_fetch import DetailFetchService
from app.storage.artifacts import ArtifactStore


async def validate_day5() -> dict[str, object]:
    settings = get_settings()
    settings.ensure_directories()
    session = SessionStore(settings.session_root / "genre_manuals.json").load()
    if session is None:
        raise RuntimeError("Stored Genre Manuals session is required")
    item = load_latest_discovered_items(settings.output_root, limit=1)[0]
    plugin = GenreManualsPlugin(
        base_url=str(settings.genre_manuals_base_url),
        navigation_timeout_ms=settings.browser_navigation_timeout_ms,
        selector_timeout_ms=settings.browser_selector_timeout_ms,
        detail_confidence_threshold=settings.disease_detail_confidence_threshold,
    )
    database = Database(settings.database_path, settings.migrations_path)
    await database.initialize()
    jobs = JobRepository(database)
    job = await jobs.create(plugin.name)
    job_id = str(job.id)
    await jobs.update_status(job_id, "running")
    items = ItemRepository(database)
    await items.upsert_discovered(job_id, [item])
    artifacts = ArtifactStore(settings.output_root)
    service = DetailFetchService(
        plugin=plugin,
        items=items,
        attempts=AttemptRepository(database),
        artifacts=artifacts,
        policy=RawFetchPolicy(
            max_attempts=settings.fetch_max_attempts,
            base_delay_seconds=settings.fetch_retry_base_seconds,
            max_delay_seconds=settings.fetch_retry_max_seconds,
            capture_screenshot=settings.capture_screenshot,
        ),
    )

    try:
        async with BrowserManager(headless=settings.browser_headless) as manager:
            context = await manager.browser.new_context(storage_state=session)
            try:
                page = await context.new_page()
                session_valid = await plugin.validate_session(page)
                if not session_valid:
                    raise RuntimeError("Stored Genre Manuals session has expired")
                graph = build_raw_fetch_graph(page=page, item=item, service=service)
                first = await graph.ainvoke(
                    {
                        "job_id": job_id,
                        "item_id": item.item_id,
                        "stage": "discovered",
                    }
                )
                resumed = await graph.ainvoke(
                    {
                        "job_id": job_id,
                        "item_id": item.item_id,
                        "stage": "fetching",
                    }
                )
            finally:
                await context.close()
        await jobs.update_status(job_id, "completed")
    except Exception:
        await jobs.update_status(job_id, "failed")
        raise

    validated = artifacts.load_valid_raw(job_id, item)
    if validated is None:
        raise RuntimeError("Day 5 artifact validation failed")
    manifest, artifact_dir = validated
    raw = manifest.artifacts["raw_html"]
    screenshot = manifest.artifacts.get("screenshot")
    attempts = await AttemptRepository(database).list_for_item(job_id, item.item_id)
    return {
        "session_valid": session_valid,
        "detail_confirmed": manifest.page_type == "disease_detail",
        "confidence": manifest.confidence,
        "raw_html_bytes": raw.size,
        "screenshot_bytes": screenshot.size if screenshot else 0,
        "checksums_valid": True,
        "attempt_records": len(attempts),
        "first_run_stage": first["stage"],
        "restart_reused_artifacts": resumed.get("reused_artifacts", False),
        "job_id": job_id,
        "item_id_prefix": item.item_id[:12],
        "artifact_dir": artifact_dir,
    }


def main() -> None:
    print(json.dumps(asyncio.run(validate_day5()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
