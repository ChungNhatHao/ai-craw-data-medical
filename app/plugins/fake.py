from playwright.async_api import Page

from app.core.config import Credentials
from app.core.ids import build_item_id
from app.models.discovery import DiscoveredItem
from app.models.navigation import NavigationCandidate, PageClassification, PageType
from app.plugins.base import SitePlugin


class FakeSitePlugin(SitePlugin):
    name = "fake"
    allowed_domains = frozenset({"example.test"})

    async def discover_demo_items(self) -> list[DiscoveredItem]:
        first = "https://example.test/diseases/alpha"
        second = "https://example.test/diseases/beta"
        return [
            DiscoveredItem(
                item_id=build_item_id(self.name, first),
                source_url=first,
                canonical_url=first,
                title_hint="Alpha",
                discovery_page="https://example.test/diseases",
            ),
            DiscoveredItem(
                item_id=build_item_id(self.name, second),
                source_url=second,
                canonical_url=second,
                title_hint="Beta",
                discovery_page="https://example.test/diseases",
            ),
        ]

    async def discover_items(self, page: Page) -> list[DiscoveredItem]:
        del page
        return await self.discover_demo_items()

    async def find_next_listing_page(
        self,
        page: Page,
        visited_pages: frozenset[str],
    ) -> NavigationCandidate | None:
        del page, visited_pages
        return None

    def canonicalize_url(self, url: str) -> str:
        return url

    async def login(self, page: Page, credentials: Credentials) -> None:
        del page, credentials

    async def validate_session(self, page: Page) -> bool:
        del page
        return True

    async def dismiss_known_popups(self, page: Page) -> int:
        del page
        return 0

    async def classify_page(self, page: Page) -> PageClassification:
        del page
        return PageClassification(
            page_type=PageType.DISEASE_DETAIL,
            confidence=1,
            matched_signals=("fake",),
            fingerprint="fake-detail-page",
        )

    async def find_next_content_candidate(
        self,
        page: Page,
        visited: frozenset[str],
    ) -> NavigationCandidate | None:
        del page, visited
        return None

    async def navigate_to_candidate(
        self,
        page: Page,
        candidate: NavigationCandidate,
    ) -> None:
        del page, candidate

    async def wait_for_detail_content(self, page: Page) -> None:
        del page
