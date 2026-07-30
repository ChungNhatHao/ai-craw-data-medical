import asyncio
from typing import Any

from app.agents.disease_detector import DiseaseDetector
from app.agents.navigation_agent import NavigationAgent
from app.core.config import Settings
from app.models.agentic import (
    DiseaseDecision,
    NavigationDecision,
    ObservedLink,
    PageObservation,
)
from app.models.discovery import DiscoveryPolicy
from app.models.navigation import PageClassification, PageType
from app.repositories.agent_audit import AgentAuditRepository
from app.repositories.database import Database
from app.repositories.items import ItemRepository
from app.repositories.jobs import JobRepository
from app.services.agentic_discovery import AgenticDiscoveryService

BASE = "https://www.genre-manuals.com"
LIST = f"{BASE}/medical"
ASTHMA = f"{BASE}/en_asthma.htm"


class FakePage:
    url = LIST

    async def go_back(self, **kwargs: Any) -> None:
        del kwargs


class FakePlugin:
    name = "genre_manuals"
    navigation_timeout_ms = 1_000

    async def classify_page(self, page: FakePage) -> PageClassification:
        page_type = (
            PageType.DISEASE_DETAIL
            if page.url == ASTHMA
            else PageType.DISEASE_LIST
        )
        return PageClassification(
            page_type=page_type,
            confidence=0.95,
            matched_signals=("fixture",),
            fingerprint=f"fingerprint-{page.url}",
        )

    async def navigate_to_candidate(
        self,
        page: FakePage,
        candidate: Any,
    ) -> None:
        page.url = candidate.target


class FakeObserver:
    async def observe(
        self,
        page: FakePage,
        *,
        visited_urls: frozenset[str],
    ) -> PageObservation:
        del visited_urls
        is_detail = page.url == ASTHMA
        return PageObservation(
            url=page.url,
            canonical_url=page.url,
            title="Asthma" if is_detail else "Medical",
            headings=("Asthma", "Symptoms") if is_detail else ("Medical",),
            main_text_excerpt=(
                "Asthma symptoms and treatment information."
                if is_detail
                else "Medical disease categories."
            ),
            medical_section_markers=(
                ("symptoms", "treatment") if is_detail else ()
            ),
            links=(
                ()
                if is_detail
                else (
                    ObservedLink(
                        candidate_id="asthma",
                        label="Asthma",
                        url=ASTHMA,
                        rule_score=0.95,
                    ),
                )
            ),
            page_fingerprint=f"observation-{page.url}",
        )

    def candidate_url(
        self,
        observation: PageObservation,
        candidate_id: str,
    ) -> str:
        return str(
            next(
                link.url
                for link in observation.links
                if link.candidate_id == candidate_id
            )
        )


class FakeAgentClient:
    async def generate_structured(
        self,
        *,
        agent_name: str,
        prompt: str,
        payload: dict[str, object],
        response_model: Any,
    ) -> Any:
        del prompt, response_model
        observation = payload["observation"]
        assert isinstance(observation, dict)
        is_detail = observation["title"] == "Asthma"
        if agent_name == "disease_detector":
            return DiseaseDecision(
                is_disease_detail=is_detail,
                confidence=0.97,
                disease_name="Asthma" if is_detail else None,
                evidence=(
                    ("Asthma symptoms and treatment information.",)
                    if is_detail
                    else ()
                ),
                negative_signals=() if is_detail else ("category",),
                reason_code=(
                    "confirmed_detail" if is_detail else "listing_page"
                ),
            )
        return NavigationDecision(
            action="stop" if is_detail else "open_candidate",
            candidate_id=None if is_detail else "asthma",
            confidence=0.95,
            reason_code="no_candidate" if is_detail else "disease_candidate",
        )


def test_agentic_discovery_requires_rule_and_gemini_confirmation(
    settings: Settings,
) -> None:
    async def scenario() -> None:
        settings.ensure_directories()
        database = Database(settings.database_path, settings.migrations_path)
        await database.initialize()
        job = await JobRepository(database).create("genre_manuals")
        repository = AgentAuditRepository(database)
        client = FakeAgentClient()

        async def progress(*args: Any) -> None:
            del args

        service = AgenticDiscoveryService(
            plugin=FakePlugin(),  # type: ignore[arg-type]
            items=ItemRepository(database),
            audit=repository,
            observer=FakeObserver(),  # type: ignore[arg-type]
            navigation_agent=NavigationAgent(client),  # type: ignore[arg-type]
            disease_detector=DiseaseDetector(client),  # type: ignore[arg-type]
            output_root=settings.output_root,
            policy=DiscoveryPolicy(max_items=1, max_pages=5),
            max_hops=4,
            disease_confidence_threshold=0.85,
        )
        items = await service.run(
            FakePage(),  # type: ignore[arg-type]
            job_id=str(job.id),
            progress=progress,
        )

        assert len(items) == 1
        assert items[0].title_hint == "Asthma"
        decisions = await repository.list_decisions(str(job.id))
        assert [record.agent_name for record in decisions] == [
            "disease_detector",
            "navigation",
            "disease_detector",
        ]
        summary = (
            settings.output_root
            / "jobs"
            / str(job.id)
            / "agent-summary.json"
        )
        assert summary.is_file()

    asyncio.run(scenario())
