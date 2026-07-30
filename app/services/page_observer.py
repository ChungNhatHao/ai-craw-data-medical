import hashlib
from typing import Protocol

from playwright.async_api import Page

from app.models.agentic import ObservedLink, PageObservation
from app.models.discovery import DiscoveryCandidate
from app.models.navigation import NavigationCandidate

MEDICAL_MARKERS = (
    "cause",
    "diagnosis",
    "prognosis",
    "risk factor",
    "signs and symptoms",
    "symptoms",
    "treatment",
)
CONTENT_ROOT = ".genrearticle, article, main, #content"
TITLE_SELECTOR = "h1, h2.pageTitle, main h2, #content h2"
BREADCRUMB_SELECTOR = "ul.breadcrumb, nav[aria-label*='breadcrumb' i], .breadcrumbs"
HEADING_SELECTOR = "h1, h2, h3, h4"


class ObservationPlugin(Protocol):
    def canonicalize_url(self, url: str) -> str: ...

    async def discover_search_candidates(
        self,
        page: Page,
        visited_urls: frozenset[str],
    ) -> list[DiscoveryCandidate]: ...

    async def find_next_content_candidate(
        self,
        page: Page,
        visited: frozenset[str],
    ) -> NavigationCandidate | None: ...


class PageObserver:
    """Build a bounded, HTML-free page snapshot for navigation agents."""

    def __init__(
        self,
        plugin: ObservationPlugin,
        *,
        max_links: int = 80,
        max_text_chars: int = 30_000,
        max_headings: int = 40,
    ) -> None:
        self.plugin = plugin
        self.max_links = max_links
        self.max_text_chars = max_text_chars
        self.max_headings = max_headings

    async def observe(
        self,
        page: Page,
        *,
        visited_urls: frozenset[str] = frozenset(),
    ) -> PageObservation:
        canonical_url = self.plugin.canonicalize_url(page.url)
        title = await self._first_text(page, TITLE_SELECTOR)
        breadcrumb = await self._texts(page, BREADCRUMB_SELECTOR, limit=20)
        headings = await self._texts(
            page,
            HEADING_SELECTOR,
            limit=self.max_headings,
        )
        main_text = await self._combined_text(page, CONTENT_ROOT)
        main_text = main_text[: self.max_text_chars]
        normalized = " ".join(main_text.casefold().split())
        markers = tuple(
            marker for marker in MEDICAL_MARKERS if marker in normalized
        )
        candidates = await self.plugin.discover_search_candidates(
            page,
            visited_urls,
        )
        deterministic_candidate = await self.plugin.find_next_content_candidate(
            page,
            visited_urls,
        )
        observed_candidates: list[
            tuple[str | None, str, str, float]
        ] = []
        if (
            deterministic_candidate is not None
            and deterministic_candidate.url is not None
        ):
            observed_candidates.append(
                (
                    deterministic_candidate.label,
                    str(deterministic_candidate.url),
                    "deterministic_navigation",
                    1,
                )
            )
        observed_candidates.extend(
            (
                candidate.label,
                str(candidate.url),
                "medical_navigation",
                candidate.score / 100,
            )
            for candidate in candidates
        )
        unique_candidates: dict[str, tuple[str | None, str, float]] = {}
        for label, url, region, score in observed_candidates:
            previous = unique_candidates.get(url)
            if previous is None or score > previous[2]:
                unique_candidates[url] = (label, region, score)
        links = tuple(
            ObservedLink(
                candidate_id=self._candidate_id(
                    canonical_url,
                    url,
                ),
                label=label,
                url=url,
                dom_region=region,
                rule_score=score,
            )
            for url, (label, region, score) in list(
                unique_candidates.items()
            )[: self.max_links]
        )
        fingerprint_source = "\n".join(
            (
                canonical_url,
                title or "",
                "|".join(headings),
                normalized[:2_000],
                "|".join(str(link.url) for link in links),
            )
        )
        fingerprint = hashlib.sha256(
            fingerprint_source.encode("utf-8")
        ).hexdigest()
        return PageObservation(
            url=page.url,
            canonical_url=canonical_url,
            title=title,
            breadcrumb=breadcrumb,
            headings=headings,
            main_text_excerpt=main_text,
            medical_section_markers=markers,
            links=links,
            page_fingerprint=fingerprint,
        )

    def candidate_url(
        self,
        observation: PageObservation,
        candidate_id: str,
    ) -> str:
        for link in observation.links:
            if link.candidate_id == candidate_id:
                return str(link.url)
        raise ValueError("Unknown navigation candidate_id")

    async def _first_text(self, page: Page, selector: str) -> str | None:
        values = await self._texts(page, selector, limit=1)
        return values[0] if values else None

    async def _texts(
        self,
        page: Page,
        selector: str,
        *,
        limit: int,
    ) -> tuple[str, ...]:
        locator = page.locator(selector)
        values: list[str] = []
        for index in range(min(await locator.count(), limit)):
            value = " ".join((await locator.nth(index).inner_text()).split())
            if value and value not in values:
                values.append(value)
        return tuple(values)

    async def _combined_text(self, page: Page, selector: str) -> str:
        locator = page.locator(selector)
        values: list[str] = []
        for index in range(await locator.count()):
            value = "\n".join(
                line.strip()
                for line in (await locator.nth(index).inner_text()).splitlines()
                if line.strip()
            )
            if value:
                values.append(value)
        return "\n".join(values)

    def _candidate_id(self, page_url: str, candidate_url: str) -> str:
        digest = hashlib.sha256(
            f"{page_url}\n{candidate_url}".encode()
        ).hexdigest()
        return f"candidate-{digest[:20]}"
