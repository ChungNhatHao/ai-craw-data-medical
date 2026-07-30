import asyncio
from typing import Any

from app.browser.session import SessionStore
from app.core.config import Credentials
from app.models.discovery import DiscoveredItem
from app.models.navigation import NavigationCandidate, PageClassification, PageType
from app.plugins.base import SitePlugin
from app.services.session import SessionService


class FakePage:
    def __init__(self, authenticated: bool) -> None:
        self.authenticated = authenticated


class FakeContext:
    def __init__(self, authenticated: bool) -> None:
        self.page = FakePage(authenticated)
        self.closed = False

    async def new_page(self) -> FakePage:
        return self.page

    async def storage_state(self) -> dict[str, Any]:
        cookies = [{"name": "session", "value": "test-only"}] if self.page.authenticated else []
        return {"cookies": cookies, "origins": []}

    async def close(self) -> None:
        self.closed = True


class FakeBrowser:
    def __init__(self) -> None:
        self.context: FakeContext | None = None

    async def new_context(self, *, storage_state: dict[str, Any] | None) -> FakeContext:
        authenticated = bool(storage_state and storage_state["cookies"])
        self.context = FakeContext(authenticated)
        return self.context


class FakeLoginPlugin(SitePlugin):
    name = "fake_login"
    allowed_domains = frozenset({"example.test"})

    def __init__(self) -> None:
        self.login_calls = 0

    async def discover_demo_items(self) -> list[DiscoveredItem]:
        return []

    async def discover_items(self, page: FakePage) -> list[DiscoveredItem]:  # type: ignore[override]
        del page
        return []

    async def find_next_listing_page(  # type: ignore[override]
        self,
        page: FakePage,
        visited_pages: frozenset[str],
    ) -> NavigationCandidate | None:
        del page, visited_pages
        return None

    def canonicalize_url(self, url: str) -> str:
        return url

    async def login(self, page: FakePage, credentials: Credentials) -> None:  # type: ignore[override]
        assert credentials.username.get_secret_value() == "user"
        self.login_calls += 1
        page.authenticated = True

    async def validate_session(self, page: FakePage) -> bool:  # type: ignore[override]
        return page.authenticated

    async def dismiss_known_popups(self, page: FakePage) -> int:  # type: ignore[override]
        del page
        return 0

    async def classify_page(self, page: FakePage) -> PageClassification:  # type: ignore[override]
        return PageClassification(
            page_type=(
                PageType.DISEASE_DETAIL if page.authenticated else PageType.LOGIN
            ),
            confidence=1,
            matched_signals=("fake",),
            fingerprint=f"fake-page-{page.authenticated}",
        )

    async def find_next_content_candidate(  # type: ignore[override]
        self,
        page: FakePage,
        visited: frozenset[str],
    ) -> NavigationCandidate | None:
        del page, visited
        return None

    async def navigate_to_candidate(  # type: ignore[override]
        self,
        page: FakePage,
        candidate: NavigationCandidate,
    ) -> None:
        del page, candidate


def test_session_service_logs_in_and_persists_new_state(tmp_path) -> None:
    async def scenario() -> None:
        store = SessionStore(tmp_path / "session.json")
        plugin = FakeLoginPlugin()
        browser = FakeBrowser()
        service = SessionService(plugin, store)

        result = await service.ensure_authenticated(  # type: ignore[arg-type]
            browser,
            Credentials(username="user", password="secret"),
        )

        assert result.reused_session is False
        assert plugin.login_calls == 1
        assert store.load() is not None
        assert browser.context is not None
        assert browser.context.closed

    asyncio.run(scenario())


def test_session_service_reuses_valid_stored_state(tmp_path) -> None:
    async def scenario() -> None:
        store = SessionStore(tmp_path / "session.json")
        store.save(
            {
                "cookies": [{"name": "session", "value": "test-only"}],
                "origins": [],
            }
        )
        plugin = FakeLoginPlugin()
        browser = FakeBrowser()

        result = await SessionService(plugin, store).ensure_authenticated(  # type: ignore[arg-type]
            browser,
            Credentials(username="user", password="secret"),
        )

        assert result.reused_session is True
        assert plugin.login_calls == 0
        assert browser.context is not None
        assert browser.context.closed

    asyncio.run(scenario())
