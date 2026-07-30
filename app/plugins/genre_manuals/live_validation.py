import asyncio
import json
from dataclasses import asdict, dataclass
from urllib.parse import urljoin

from app.browser.manager import BrowserManager
from app.browser.session import SessionStore
from app.core.config import get_settings
from app.models.discovery import DiscoveryPolicy
from app.models.navigation import NavigationPolicy, PageType
from app.plugins.genre_manuals.plugin import GenreManualsPlugin
from app.repositories.database import Database
from app.repositories.items import ItemRepository
from app.repositories.jobs import JobRepository
from app.services.discovery import DiscoveryService
from app.services.navigation import NavigationDetectionLoop


@dataclass(frozen=True)
class LiveValidationSummary:
    session_valid: bool
    day3_detail_confirmed: bool
    day3_hops: int
    day3_candidates_visited: int
    day4_listing_confirmed: bool
    day4_items_discovered: int
    day4_pages_visited: int
    day4_stopped_reason: str
    day4_limits_reached: tuple[str, ...]
    job_id: str
    export_path: str


async def validate_day3_and_day4() -> LiveValidationSummary:
    settings = get_settings()
    settings.ensure_directories()
    plugin = GenreManualsPlugin(
        base_url=str(settings.genre_manuals_base_url),
        navigation_timeout_ms=settings.browser_navigation_timeout_ms,
        selector_timeout_ms=settings.browser_selector_timeout_ms,
        detail_confidence_threshold=settings.disease_detail_confidence_threshold,
    )
    session = SessionStore(
        settings.session_root / "genre_manuals.json"
    ).load()
    if session is None:
        raise RuntimeError("Stored Genre Manuals session is required")

    database = Database(settings.database_path, settings.migrations_path)
    await database.initialize()
    job = await JobRepository(database).create(plugin.name)
    job_id = str(job.id)

    async with BrowserManager(headless=settings.browser_headless) as manager:
        context = await manager.browser.new_context(storage_state=session)
        try:
            page = await context.new_page()
            session_valid = await plugin.validate_session(page)
            if not session_valid:
                raise RuntimeError("Stored Genre Manuals session has expired")

            navigation = NavigationDetectionLoop(
                plugin,
                NavigationPolicy(
                    max_hops=settings.navigation_max_hops_per_item,
                    max_same_fingerprint=settings.navigation_max_same_fingerprint,
                    max_no_progress=settings.navigation_max_no_progress,
                ),
            )
            day3 = await navigation.locate_disease_detail(page)
            day3_confirmed = (
                day3.classification.page_type is PageType.DISEASE_DETAIL
                and day3.classification.confidence
                >= settings.disease_detail_confidence_threshold
            )
            if not day3_confirmed:
                raise RuntimeError("Day 3 did not reach a confirmed disease detail")

            listing_url = urljoin(
                str(settings.genre_manuals_base_url),
                (
                    "home/page7/page8/circulatory-system/"
                    "arteries-arterioles-and-capillar.html"
                ),
            )
            await page.goto(
                listing_url,
                wait_until="domcontentloaded",
                timeout=settings.browser_navigation_timeout_ms,
            )
            listing = await plugin.classify_page(page)
            listing_confirmed = listing.page_type is PageType.DISEASE_LIST
            if not listing_confirmed:
                raise RuntimeError(
                    "Expected authenticated medical listing was classified as "
                    f"{listing.page_type.value}"
                )

            discovery = await DiscoveryService(
                plugin,
                ItemRepository(database),
                settings.output_root,
                DiscoveryPolicy(
                    max_items=min(settings.crawl_max_items, 25),
                    max_pages=min(settings.crawl_max_pages, 5),
                    max_no_new_rounds=settings.discovery_max_no_new_rounds,
                ),
            ).run(page, job_id)
            if not discovery.items:
                raise RuntimeError("Day 4 did not discover any disease items")
        finally:
            await context.close()

    export_path = settings.output_root / "jobs" / job_id / "disease-list.json"
    return LiveValidationSummary(
        session_valid=session_valid,
        day3_detail_confirmed=day3_confirmed,
        day3_hops=day3.hop_count,
        day3_candidates_visited=len(day3.visited_candidates),
        day4_listing_confirmed=listing_confirmed,
        day4_items_discovered=len(discovery.items),
        day4_pages_visited=discovery.pages_visited,
        day4_stopped_reason=discovery.stopped_reason,
        day4_limits_reached=discovery.limits_reached,
        job_id=job_id,
        export_path=str(export_path),
    )


def main() -> None:
    summary = asyncio.run(validate_day3_and_day4())
    print(json.dumps(asdict(summary), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
