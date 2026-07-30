import asyncio

from app.browser.manager import BrowserManager
from app.browser.session import SessionStore
from app.core.config import get_settings
from app.plugins.genre_manuals.plugin import GenreManualsPlugin
from app.services.session import SessionService


async def login_and_persist_session() -> bool:
    settings = get_settings()
    settings.ensure_directories()
    credentials = settings.require_genre_manuals_credentials()
    plugin = GenreManualsPlugin(
        base_url=str(settings.genre_manuals_base_url),
        navigation_timeout_ms=settings.browser_navigation_timeout_ms,
        selector_timeout_ms=settings.browser_selector_timeout_ms,
    )
    session_store = SessionStore(settings.session_root / "genre_manuals.json")

    async with BrowserManager(headless=settings.browser_headless) as manager:
        result = await SessionService(plugin, session_store).ensure_authenticated(
            manager.browser,
            credentials,
        )
    return result.reused_session


def main() -> None:
    reused_session = asyncio.run(login_and_persist_session())
    outcome = "reused existing session" if reused_session else "created new session"
    print(f"Genre Manuals login passed: {outcome}")


if __name__ == "__main__":
    main()

