import asyncio

from app.browser.manager import BrowserManager
from app.core.config import get_settings
from app.models.navigation import PageType
from app.plugins.genre_manuals.plugin import GenreManualsPlugin

PUBLIC_NON_DISEASE_URL = (
    "https://www.genre-manuals.com/sites/CLUE/home/financial.html"
)


async def check_public_page_classification() -> tuple[PageType, PageType, int]:
    settings = get_settings()
    plugin = GenreManualsPlugin(
        base_url=str(settings.genre_manuals_base_url),
        navigation_timeout_ms=settings.browser_navigation_timeout_ms,
        selector_timeout_ms=settings.browser_selector_timeout_ms,
        detail_confidence_threshold=settings.disease_detail_confidence_threshold,
    )
    async with BrowserManager(headless=settings.browser_headless) as manager:
        context = await manager.browser.new_context()
        try:
            page = await context.new_page()
            await page.goto(str(settings.genre_manuals_base_url))
            login_type = (await plugin.classify_page(page)).page_type
            await page.goto(PUBLIC_NON_DISEASE_URL)
            non_disease_type = (await plugin.classify_page(page)).page_type
            non_disease_items = await plugin.discover_items(page)
            return login_type, non_disease_type, len(non_disease_items)
        finally:
            await context.close()


def main() -> None:
    login_type, non_disease_type, discovered_count = asyncio.run(
        check_public_page_classification()
    )
    if login_type is not PageType.LOGIN:
        raise SystemExit(f"Expected login page, received {login_type.value}")
    if non_disease_type is PageType.DISEASE_DETAIL:
        raise SystemExit("Public financial page was incorrectly classified as disease")
    if discovered_count:
        raise SystemExit("Public financial links were incorrectly discovered as diseases")
    print(
        "Genre Manuals navigation classifier smoke check passed: "
        f"{login_type.value}, {non_disease_type.value}, "
        f"{discovered_count} false disease items"
    )


if __name__ == "__main__":
    main()
