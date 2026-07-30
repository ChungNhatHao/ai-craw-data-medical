import asyncio
import json
from urllib.parse import urljoin

from playwright.async_api import StorageState

from app.browser.manager import BrowserManager
from app.browser.session import SessionStore
from app.core.config import get_settings
from app.core.ids import build_item_id
from app.models.artifacts import RawFetchPolicy
from app.models.batch import BatchPolicy, BatchResult
from app.models.discovery import DiscoveredItem
from app.plugins.genre_manuals.live_support import load_latest_discovered_items
from app.plugins.genre_manuals.plugin import GenreManualsPlugin
from app.repositories.attempts import AttemptRepository
from app.repositories.database import Database
from app.repositories.items import ItemRepository
from app.repositories.jobs import JobRepository
from app.services.batch import BatchFetchService
from app.services.detail_fetch import DetailFetchService
from app.storage.artifacts import ArtifactStore


async def _run_phase(
    *,
    session: StorageState,
    plugin: GenreManualsPlugin,
    batch: BatchFetchService,
    job_id: str,
    headless: bool,
) -> tuple[BatchResult, bool, bool]:
    manager = BrowserManager(headless=headless)
    session_valid = False
    async with manager:
        context = await manager.browser.new_context(storage_state=session)
        try:
            page = await context.new_page()
            session_valid = await plugin.validate_session(page)
            if not session_valid:
                raise RuntimeError("Stored Genre Manuals session has expired")
            result = await batch.run(page, job_id=job_id)
        finally:
            await context.close()
    try:
        _ = manager.browser
    except RuntimeError:
        browser_cleaned = True
    else:
        browser_cleaned = False
    return result, session_valid, browser_cleaned


async def validate_day6() -> dict[str, object]:
    settings = get_settings()
    settings.ensure_directories()
    session = SessionStore(settings.session_root / "genre_manuals.json").load()
    if session is None:
        raise RuntimeError("Stored Genre Manuals session is required")
    live_items = load_latest_discovered_items(settings.output_root, limit=2)
    controlled_url = urljoin(
        str(settings.genre_manuals_base_url),
        "home/financial.html",
    )
    controlled_failure = DiscoveredItem(
        item_id=build_item_id("genre_manuals", controlled_url),
        source_url=controlled_url,
        canonical_url=controlled_url,
        title_hint="Controlled non-disease validation",
        discovery_page=str(settings.genre_manuals_base_url),
    )

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
    items = ItemRepository(database)
    await items.upsert_discovered(job_id, [*live_items, controlled_failure])
    attempts = AttemptRepository(database)
    artifacts = ArtifactStore(settings.output_root)
    detail_fetch = DetailFetchService(
        plugin=plugin,
        items=items,
        attempts=attempts,
        artifacts=artifacts,
        policy=RawFetchPolicy(
            max_attempts=settings.fetch_max_attempts,
            base_delay_seconds=settings.fetch_retry_base_seconds,
            max_delay_seconds=settings.fetch_retry_max_seconds,
            capture_screenshot=settings.capture_screenshot,
        ),
    )

    phase_one, valid_one, cleaned_one = await _run_phase(
        session=session,
        plugin=plugin,
        batch=BatchFetchService(
            jobs=jobs,
            items=items,
            artifacts=artifacts,
            detail_fetch=detail_fetch,
            policy=BatchPolicy(max_items=1),
        ),
        job_id=job_id,
        headless=settings.browser_headless,
    )
    phase_two, valid_two, cleaned_two = await _run_phase(
        session=session,
        plugin=plugin,
        batch=BatchFetchService(
            jobs=jobs,
            items=items,
            artifacts=artifacts,
            detail_fetch=detail_fetch,
            policy=BatchPolicy(max_items=10),
        ),
        job_id=job_id,
        headless=settings.browser_headless,
    )

    counts = await items.count_by_status(job_id)
    valid_artifacts = sum(
        artifacts.load_valid_raw(job_id, item) is not None for item in live_items
    )
    histories = {
        item.item_id: await attempts.list_for_item(job_id, item.item_id)
        for item in [*live_items, controlled_failure]
    }
    return {
        "session_valid_both_phases": valid_one and valid_two,
        "phase_one_status": phase_one.status.value,
        "phase_one_processed": phase_one.processed_count,
        "phase_one_remaining": phase_one.remaining_count,
        "phase_one_reason": phase_one.stopped_reason,
        "phase_two_status": phase_two.status.value,
        "phase_two_processed": phase_two.processed_count,
        "phase_two_fetched": phase_two.fetched_count,
        "phase_two_failed": phase_two.failed_count,
        "phase_two_reason": phase_two.stopped_reason,
        "browser_cleanup_both_phases": cleaned_one and cleaned_two,
        "final_item_counts": counts,
        "valid_raw_artifact_sets": valid_artifacts,
        "first_item_attempt_records": len(histories[live_items[0].item_id]),
        "controlled_failure_code": (
            histories[controlled_failure.item_id][-1].error_code
            if histories[controlled_failure.item_id]
            else None
        ),
        "job_id": job_id,
        "artifact_root": f"jobs/{job_id}/items",
    }


def main() -> None:
    print(json.dumps(asyncio.run(validate_day6()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
