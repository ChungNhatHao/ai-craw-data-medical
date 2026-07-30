import asyncio
import json

from app.core.config import Settings
from app.models.discovery import DiscoveryCandidate, DiscoveryPolicy
from app.models.navigation import (
    NavigationCandidate,
    PageClassification,
    PageType,
)
from app.repositories.database import Database
from app.repositories.items import ItemRepository
from app.repositories.jobs import JobRepository
from app.services.intelligent_discovery import IntelligentDiscoveryService

BASE = "https://www.genre-manuals.com"
HOME = f"{BASE}/medical"
LIST = f"{BASE}/respiratory"
ASTHMA = f"{BASE}/en_asthma.htm"
COPD = f"{BASE}/en_copd.htm"


class FakeLocator:
    def __init__(self, text: str) -> None:
        self.text = text

    @property
    def first(self) -> "FakeLocator":
        return self

    async def count(self) -> int:
        return 1

    async def inner_text(self) -> str:
        return self.text


class FakePage:
    def __init__(self) -> None:
        self.url = HOME
        self.titles = {
            HOME: "Medical",
            LIST: "Respiratory system",
            ASTHMA: "Asthma",
            COPD: "COPD",
        }

    def locator(self, selector: str) -> FakeLocator:
        del selector
        return FakeLocator(self.titles[self.url])


class FakePlugin:
    name = "genre_manuals"
    detail_confidence_threshold = 0.8

    def canonicalize_url(self, url: str) -> str:
        return url

    def content_title_selectors(self) -> tuple[str, ...]:
        return ("h1",)

    async def classify_page(self, page: FakePage) -> PageClassification:
        page_type = (
            PageType.DISEASE_DETAIL
            if page.url in {ASTHMA, COPD}
            else PageType.DISEASE_LIST
        )
        return PageClassification(
            page_type=page_type,
            confidence=0.95,
            matched_signals=("semantic_medical_content",),
            fingerprint=f"fingerprint-{page.url}",
        )

    async def discover_search_candidates(
        self,
        page: FakePage,
        visited_urls: frozenset[str],
    ) -> list[DiscoveryCandidate]:
        graph = {
            HOME: [(LIST, "Respiratory system", 80)],
            LIST: [(ASTHMA, "Asthma", 95), (COPD, "COPD", 95)],
            ASTHMA: [],
            COPD: [],
        }
        return [
            DiscoveryCandidate(
                url=url,
                label=label,
                score=score,
                source_url=page.url,
            )
            for url, label, score in graph[page.url]
            if url not in visited_urls
        ]

    async def navigate_to_candidate(
        self,
        page: FakePage,
        candidate: NavigationCandidate,
    ) -> None:
        page.url = candidate.target

    async def dismiss_known_popups(self, page: FakePage) -> int:
        del page
        return 0


def test_intelligent_discovery_expands_lists_and_verifies_details(
    settings: Settings,
) -> None:
    async def scenario() -> None:
        settings.ensure_directories()
        database = Database(settings.database_path, settings.migrations_path)
        await database.initialize()
        job = await JobRepository(database).create("genre_manuals")
        progress_events: list[tuple[int, int, int, str]] = []

        async def progress(
            accepted: int,
            evaluated: int,
            queued: int,
            page_type: str,
        ) -> None:
            progress_events.append((accepted, evaluated, queued, page_type))

        service = IntelligentDiscoveryService(
            plugin=FakePlugin(),  # type: ignore[arg-type]
            items=ItemRepository(database),
            output_root=settings.output_root,
            policy=DiscoveryPolicy(max_items=2, max_pages=10),
        )
        result = await service.run(
            FakePage(),  # type: ignore[arg-type]
            job_id=str(job.id),
            progress=progress,
        )

        assert [item.title_hint for item in result.items] == ["Asthma", "COPD"]
        assert result.pages_evaluated == 4
        assert result.stopped_reason == "max_items"
        assert len(result.evaluations) == 4
        assert sum(item.accepted for item in result.evaluations) == 2
        assert progress_events[-1][0] == 2

        audit_path = (
            settings.output_root / "jobs" / str(job.id) / "ai-discovery.json"
        )
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        assert audit["mode"] == "hybrid_semantic_graph"
        assert audit["pages_evaluated"] == 4

    asyncio.run(scenario())
