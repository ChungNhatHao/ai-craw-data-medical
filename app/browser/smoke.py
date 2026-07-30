import asyncio

from app.browser.manager import BrowserManager
from app.core.config import get_settings


async def run_smoke_check() -> bool:
    settings = get_settings()
    async with BrowserManager(headless=settings.browser_headless) as manager:
        return await manager.smoke_check()


def main() -> None:
    if not asyncio.run(run_smoke_check()):
        raise SystemExit(1)
    print("Playwright Chromium smoke check passed")


if __name__ == "__main__":
    main()

