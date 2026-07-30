import asyncio
from typing import Any

from app.browser.manager import BrowserManager


class FakeLocator:
    async def inner_text(self) -> str:
        return "crawler-ready"


class FakePage:
    closed = False

    async def set_content(self, content: str) -> None:
        assert "crawler-ready" in content

    def locator(self, selector: str) -> FakeLocator:
        assert selector == "main"
        return FakeLocator()

    async def close(self) -> None:
        self.closed = True


class FakeBrowser:
    closed = False

    async def new_page(self) -> FakePage:
        return FakePage()

    async def close(self) -> None:
        self.closed = True


class FakeChromium:
    def __init__(self, browser: FakeBrowser) -> None:
        self.browser = browser

    async def launch(self, *, headless: bool) -> FakeBrowser:
        assert headless
        return self.browser


class FakePlaywright:
    def __init__(self, browser: FakeBrowser) -> None:
        self.chromium = FakeChromium(browser)

    async def stop(self) -> None:
        return None


class FakeManager:
    def __init__(self, runtime: FakePlaywright) -> None:
        self.runtime = runtime

    async def start(self) -> FakePlaywright:
        return self.runtime


def test_browser_manager_smoke_check_and_cleanup(
    tmp_path: Any,
    monkeypatch: Any,
) -> None:
    async def scenario() -> None:
        browser = FakeBrowser()
        runtime = FakePlaywright(browser)
        browser_path = tmp_path / ".playwright-browsers"
        browser_path.mkdir()
        monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)

        def factory() -> Any:
            return FakeManager(runtime)

        manager = BrowserManager(
            playwright_factory=factory,
            browser_path=browser_path,
        )
        assert await manager.smoke_check()
        assert (
            __import__("os").environ["PLAYWRIGHT_BROWSERS_PATH"]
            == str(browser_path)
        )
        await manager.close()
        assert browser.closed

    asyncio.run(scenario())
