import json
import os
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path

from playwright.async_api import Page

from app.agents.agentic_graph import build_agentic_step_graph
from app.agents.disease_detector import DiseaseDetector
from app.agents.navigation_agent import NavigationAgent
from app.core.errors import CrawlerError, ErrorCode
from app.core.ids import build_item_id
from app.models.agentic import DiseaseDecision, NavigationDecision
from app.models.discovery import DiscoveredItem, DiscoveryPolicy
from app.models.navigation import NavigationCandidate, PageType
from app.plugins.genre_manuals.plugin import GenreManualsPlugin
from app.repositories.agent_audit import AgentAuditRepository
from app.repositories.items import ItemRepository
from app.services.page_observer import PageObserver

AgenticProgress = Callable[[int, int, int, str], Awaitable[None]]


class AgenticDiscoveryService:
    """Gemini-guided discovery with deterministic browser and page guards."""

    def __init__(
        self,
        *,
        plugin: GenreManualsPlugin,
        items: ItemRepository,
        audit: AgentAuditRepository,
        observer: PageObserver,
        navigation_agent: NavigationAgent,
        disease_detector: DiseaseDetector,
        output_root: Path,
        policy: DiscoveryPolicy,
        max_hops: int,
        disease_confidence_threshold: float,
    ) -> None:
        self.plugin = plugin
        self.items = items
        self.audit = audit
        self.observer = observer
        self.navigation_agent = navigation_agent
        self.disease_detector = disease_detector
        self.output_root = output_root
        self.policy = policy
        self.max_hops = max_hops
        self.disease_confidence_threshold = disease_confidence_threshold

    async def run(
        self,
        page: Page,
        *,
        job_id: str,
        progress: AgenticProgress,
    ) -> list[DiscoveredItem]:
        accepted: dict[str, DiscoveredItem] = {}
        visited_urls: set[str] = set()
        visited_page_states: set[str] = set()
        visited_candidate_ids: set[str] = set()
        hop_count = 0
        stop_reason = "page_budget_exhausted"
        step_graph = build_agentic_step_graph(
            page=page,
            plugin=self.plugin,
            observer=self.observer,
            disease_detector=self.disease_detector,
            navigation_agent=self.navigation_agent,
            disease_confidence_threshold=self.disease_confidence_threshold,
        )

        for page_count in range(1, self.policy.max_pages + 1):
            step = await step_graph.ainvoke(
                {
                    "visited_urls": tuple(sorted(visited_urls)),
                    "visited_candidate_ids": tuple(
                        sorted(visited_candidate_ids)
                    ),
                    "remaining_hops": self.max_hops - hop_count,
                }
            )
            observation = step["observation"]
            current_url = str(observation.canonical_url)
            if observation.page_fingerprint in visited_page_states:
                stop_reason = "repeated_page_state"
                break
            visited_page_states.add(observation.page_fingerprint)
            visited_urls.add(current_url)

            page_type = step["page_type"]
            self._raise_terminal_page(page_type)
            disease_decision = step["disease_decision"]
            await self._record_disease_decision(
                job_id,
                observation.page_fingerprint,
                disease_decision,
            )
            accepted_page = step["accepted"]
            if accepted_page:
                item = DiscoveredItem(
                    item_id=build_item_id(self.plugin.name, current_url),
                    source_url=current_url,
                    canonical_url=current_url,
                    title_hint=disease_decision.disease_name,
                    discovery_page=current_url,
                )
                if item.item_id not in accepted:
                    accepted[item.item_id] = item
                    await self.items.upsert_discovered(job_id, [item])
            await progress(
                len(accepted),
                page_count,
                hop_count,
                (
                    "confirmed_detail"
                    if accepted_page
                    else disease_decision.reason_code
                ),
            )
            if len(accepted) >= self.policy.max_items:
                stop_reason = "max_items"
                break
            if hop_count >= self.max_hops:
                stop_reason = "max_hops"
                break

            navigation_decision = step.get("navigation_decision")
            if navigation_decision is None:
                navigation_decision = await self.navigation_agent.decide(
                    observation,
                    visited_candidate_ids=frozenset(
                        visited_candidate_ids
                    ),
                    remaining_hops=self.max_hops - hop_count,
                )
            if (
                accepted_page
                and navigation_decision.action == "stop"
                and hop_count < self.max_hops
            ):
                navigation_decision = NavigationDecision(
                    action="go_back",
                    confidence=navigation_decision.confidence,
                    reason_code="no_candidate",
                )
            await self._record_navigation_decision(
                job_id,
                observation.page_fingerprint,
                navigation_decision,
            )
            if navigation_decision.action == "stop":
                stop_reason = navigation_decision.reason_code
                break
            if navigation_decision.action == "needs_operator":
                raise CrawlerError(
                    ErrorCode.AGENT_ACTION_INVALID,
                    "Navigation Agent requested operator intervention",
                )
            if navigation_decision.action == "go_back":
                await page.go_back(
                    wait_until="domcontentloaded",
                    timeout=self.plugin.navigation_timeout_ms,
                )
                hop_count += 1
                continue
            candidate_id = navigation_decision.candidate_id
            if candidate_id is None:
                raise CrawlerError(
                    ErrorCode.AGENT_ACTION_INVALID,
                    "Navigation Agent omitted candidate_id",
                )
            target = self.observer.candidate_url(observation, candidate_id)
            visited_candidate_ids.add(candidate_id)
            await self.plugin.navigate_to_candidate(
                page,
                NavigationCandidate(
                    key=target,
                    action="goto",
                    target=target,
                    label=candidate_id,
                    url=target,
                ),
            )
            hop_count += 1
        else:
            stop_reason = "max_pages"

        persisted = await self.items.list_for_job(job_id)
        self._export_summary(
            job_id=job_id,
            items=persisted,
            pages_evaluated=len(visited_urls),
            hop_count=hop_count,
            stop_reason=stop_reason,
        )
        return persisted

    def _raise_terminal_page(self, page_type: PageType) -> None:
        if page_type is PageType.LOGIN:
            raise CrawlerError(
                ErrorCode.AUTH_SESSION_EXPIRED,
                "Agentic discovery returned to login",
            )
        if page_type is PageType.BLOCKED_OR_CAPTCHA:
            raise CrawlerError(
                ErrorCode.AUTH_MFA_OR_CAPTCHA,
                "Agentic discovery encountered a blocked page",
            )

    async def _record_disease_decision(
        self,
        job_id: str,
        page_fingerprint: str,
        decision: DiseaseDecision,
    ) -> None:
        await self.audit.record_decision(
            job_id=job_id,
            agent_name="disease_detector",
            page_fingerprint=page_fingerprint,
            decision=decision.model_dump(mode="json"),
            confidence=decision.confidence,
        )

    async def _record_navigation_decision(
        self,
        job_id: str,
        page_fingerprint: str,
        decision: NavigationDecision,
    ) -> None:
        await self.audit.record_decision(
            job_id=job_id,
            agent_name="navigation",
            page_fingerprint=page_fingerprint,
            decision=decision.model_dump(mode="json"),
            confidence=decision.confidence,
        )

    def _export_summary(
        self,
        *,
        job_id: str,
        items: list[DiscoveredItem],
        pages_evaluated: int,
        hop_count: int,
        stop_reason: str,
    ) -> None:
        output = self.output_root / "jobs" / job_id
        output.mkdir(parents=True, exist_ok=True)
        payload = {
            "job_id": job_id,
            "mode": "gemini_agentic",
            "pages_evaluated": pages_evaluated,
            "navigation_hops": hop_count,
            "stop_reason": stop_reason,
            "count": len(items),
            "items": [item.model_dump(mode="json") for item in items],
        }
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=output,
                prefix=".agent-summary.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                json.dump(payload, temporary, ensure_ascii=False, indent=2)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, output / "agent-summary.json")
        except Exception:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise
