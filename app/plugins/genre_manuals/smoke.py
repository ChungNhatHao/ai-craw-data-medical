import asyncio

from app.browser.manager import BrowserManager
from app.core.config import get_settings
from app.plugins.genre_manuals.plugin import GenreManualsPlugin


async def check_public_login_page() -> bool:
    settings = get_settings()
    plugin = GenreManualsPlugin(
        base_url=str(settings.genre_manuals_base_url),
        navigation_timeout_ms=settings.browser_navigation_timeout_ms,
        selector_timeout_ms=settings.browser_selector_timeout_ms,
    )
    async with BrowserManager(headless=settings.browser_headless) as manager:
        context = await manager.browser.new_context()
        try:
            page = await context.new_page()
            return not await plugin.validate_session(page)
        finally:
            await context.close()


def main() -> None:
    if not asyncio.run(check_public_login_page()):
        raise SystemExit("Expected the public page to require login")
    print("Genre Manuals public login/session validation smoke check passed")


if __name__ == "__main__":
    main()

