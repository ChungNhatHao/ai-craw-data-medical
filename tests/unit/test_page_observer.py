import asyncio
from typing import Any

from app.models.discovery import DiscoveryCandidate
from app.models.navigation import NavigationCandidate
from app.services.page_observer import PageObserver

PAGE_URL = "https://www.genre-manuals.com/medical"
DETAIL_URL = "https://www.genre-manuals.com/en_asthma.htm"


class FakeLocator:
    def __init__(self, values: list[str]) -> None:
        self.values = values
        self.index: int | None = None

    def nth(self, index: int) -> "FakeLocator":
        selected = FakeLocator(self.values)
        selected.index = index
        return selected

    async def count(self) -> int:
        return len(self.values)

    async def inner_text(self) -> str:
        assert self.index is not None
        return self.values[self.index]


class FakePage:
    url = PAGE_URL

    def locator(self, selector: str) -> FakeLocator:
        if "breadcrumb" in selector:
            return FakeLocator(["Home Medical Ratings"])
        if selector == "h1, h2, h3, h4":
            return FakeLocator(["Respiratory diseases", "Symptoms"])
        if selector.startswith("h1"):
            return FakeLocator(["Respiratory diseases"])
        return FakeLocator(
            ["Asthma symptoms diagnosis and treatment information."]
        )


class FakePlugin:
    def canonicalize_url(self, url: str) -> str:
        return url

    async def discover_search_candidates(
        self,
        page: Any,
        visited_urls: frozenset[str],
    ) -> list[DiscoveryCandidate]:
        del page, visited_urls
        return [
            DiscoveryCandidate(
                url=DETAIL_URL,
                label="Asthma",
                score=95,
                source_url=PAGE_URL,
            )
        ]

    async def find_next_content_candidate(
        self,
        page: Any,
        visited: frozenset[str],
    ) -> NavigationCandidate | None:
        del page, visited
        return None


def test_page_observer_builds_bounded_html_free_snapshot() -> None:
    async def scenario() -> None:
        observer = PageObserver(FakePlugin())  # type: ignore[arg-type]
        observation = await observer.observe(FakePage())  # type: ignore[arg-type]

        assert observation.title == "Respiratory diseases"
        assert "symptoms" in observation.medical_section_markers
        assert observation.links[0].label == "Asthma"
        assert observation.links[0].rule_score == 0.95
        assert "<" not in observation.main_text_excerpt
        assert len(observation.page_fingerprint) == 64
        assert (
            observer.candidate_url(
                observation,
                observation.links[0].candidate_id,
            )
            == DETAIL_URL
        )

    asyncio.run(scenario())
