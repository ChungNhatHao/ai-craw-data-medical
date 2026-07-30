import os
from pathlib import Path
from types import TracebackType
from typing import Any

from playwright.async_api import Browser, Playwright, async_playwright
from playwright.async_api import Error as PlaywrightError

from app.core.errors import CrawlerError, ErrorCode


class BrowserManager:
    """Own exactly one Playwright runtime and browser process."""

    def __init__(
        self,
        *,
        headless: bool = True,
        playwright_factory: Any = async_playwright,
        browser_path: Path | None = None,
    ) -> None:
        self._headless = headless
        self._playwright_factory = playwright_factory
        self._browser_path = (
            browser_path
            if browser_path is not None
            else Path(__file__).resolve().parents[2] / ".playwright-browsers"
        )
        self._runtime: Playwright | None = None
        self._browser: Browser | None = None

    @property
    def browser(self) -> Browser:
        if self._browser is None:
            raise RuntimeError("BrowserManager has not been started")
        return self._browser

    async def start(self) -> Browser:
        if self._browser is not None:
            return self._browser
        if (
            "PLAYWRIGHT_BROWSERS_PATH" not in os.environ
            and self._browser_path.is_dir()
        ):
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(self._browser_path)
        try:
            manager = self._playwright_factory()
            self._runtime = await manager.start()
            self._browser = await self._runtime.chromium.launch(
                headless=self._headless
            )
        except (OSError, PlaywrightError) as exc:
            if self._runtime is not None:
                await self._runtime.stop()
                self._runtime = None
            raise CrawlerError(
                ErrorCode.BROWSER_UNAVAILABLE,
                (
                    "Không tìm thấy Chromium runtime. Hãy cấu hình "
                    "PLAYWRIGHT_BROWSERS_PATH hoặc chạy playwright install chromium"
                ),
            ) from exc
        return self._browser

    async def smoke_check(self) -> bool:
        browser = await self.start()
        page = await browser.new_page()
        try:
            await page.set_content("<main>crawler-ready</main>")
            return await page.locator("main").inner_text() == "crawler-ready"
        finally:
            await page.close()

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._runtime is not None:
            await self._runtime.stop()
            self._runtime = None

    async def __aenter__(self) -> "BrowserManager":
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()
