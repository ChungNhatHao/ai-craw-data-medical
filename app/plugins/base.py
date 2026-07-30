from abc import ABC, abstractmethod

from playwright.async_api import Locator, Page

from app.core.config import Credentials
from app.models.discovery import DiscoveredItem
from app.models.navigation import NavigationCandidate, PageClassification
from app.models.tabs import RawDiseaseTab


class SitePlugin(ABC):
    name: str
    allowed_domains: frozenset[str]

    @abstractmethod
    async def discover_demo_items(self) -> list[DiscoveredItem]:
        """Day-1 seam; replaced by browser-backed discovery on Day 4."""

    @abstractmethod
    async def discover_items(self, page: Page) -> list[DiscoveredItem]:
        """Discover canonical disease items from the current listing page."""

    @abstractmethod
    async def find_next_listing_page(
        self,
        page: Page,
        visited_pages: frozenset[str],
    ) -> NavigationCandidate | None:
        """Return the next unvisited pagination candidate."""

    @abstractmethod
    def canonicalize_url(self, url: str) -> str:
        """Return the stable canonical URL used for identity and deduplication."""

    @abstractmethod
    async def login(self, page: Page, credentials: Credentials) -> None:
        """Authenticate the current browser context."""

    @abstractmethod
    async def validate_session(self, page: Page) -> bool:
        """Return whether the current browser context is authenticated."""

    @abstractmethod
    async def dismiss_known_popups(self, page: Page) -> int:
        """Dismiss only allowlisted non-destructive overlays."""

    @abstractmethod
    async def classify_page(self, page: Page) -> PageClassification:
        """Classify the current page before any content crawl."""

    @abstractmethod
    async def find_next_content_candidate(
        self,
        page: Page,
        visited: frozenset[str],
    ) -> NavigationCandidate | None:
        """Return the best unvisited candidate toward disease content."""

    @abstractmethod
    async def navigate_to_candidate(
        self,
        page: Page,
        candidate: NavigationCandidate,
    ) -> None:
        """Execute one allowlisted navigation candidate."""

    async def wait_for_detail_content(self, page: Page) -> None:
        """Wait until the plugin's disease content-ready condition is satisfied."""
        del page
        raise NotImplementedError

    async def screenshot_masks(self, page: Page) -> list[Locator]:
        """Return plugin-owned regions that must be masked in evidence images."""
        del page
        return []

    async def capture_detail_tabs(
        self,
        page: Page,
    ) -> tuple[RawDiseaseTab, ...]:
        """Capture plugin-specific raw tab fragments from a confirmed detail page."""
        del page
        return ()

    def content_root_selectors(self) -> tuple[str, ...]:
        """Return ordered selectors for offline main-content extraction."""
        return ("article", "main", "#content")

    def content_title_selectors(self) -> tuple[str, ...]:
        """Return ordered selectors for the disease title."""
        return ("h1", "h2")
