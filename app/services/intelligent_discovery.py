import heapq
import json
import os
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path

from playwright.async_api import Page

from app.core.errors import CrawlerError, ErrorCode
from app.core.ids import build_item_id
from app.models.discovery import (
    DiscoveredItem,
    DiscoveryCandidate,
    DiscoveryEvaluation,
    DiscoveryPolicy,
    IntelligentDiscoveryResult,
)
from app.models.navigation import NavigationCandidate, PageType
from app.plugins.genre_manuals.plugin import GenreManualsPlugin
from app.repositories.items import ItemRepository

DiscoveryProgress = Callable[[int, int, int, str], Awaitable[None]]


class IntelligentDiscoveryService:
    """Explore the medical navigation graph and verify every accepted page."""

    def __init__(
        self,
        *,
        plugin: GenreManualsPlugin,
        items: ItemRepository,
        output_root: Path,
        policy: DiscoveryPolicy,
    ) -> None:
        self.plugin = plugin
        self.items = items
        self.output_root = output_root
        self.policy = policy

    async def run(
        self,
        page: Page,
        *,
        job_id: str,
        progress: DiscoveryProgress,
    ) -> IntelligentDiscoveryResult:
        accepted: dict[str, DiscoveredItem] = {}
        evaluated_urls: set[str] = set()
        queued_urls: set[str] = set()
        evaluations: list[DiscoveryEvaluation] = []
        queue: list[tuple[int, int, DiscoveryCandidate]] = []
        sequence = 0

        async def enqueue_from_current_page() -> None:
            nonlocal sequence
            candidates = await self.plugin.discover_search_candidates(
                page,
                frozenset(evaluated_urls | queued_urls),
            )
            for candidate in candidates:
                url = str(candidate.url)
                if url in evaluated_urls or url in queued_urls:
                    continue
                queued_urls.add(url)
                sequence += 1
                heapq.heappush(queue, (-candidate.score, sequence, candidate))

        async def evaluate_current(label: str | None) -> None:
            current_url = self.plugin.canonicalize_url(page.url)
            if current_url in evaluated_urls:
                return
            evaluated_urls.add(current_url)
            classification = await self.plugin.classify_page(page)
            is_disease = (
                classification.page_type is PageType.DISEASE_DETAIL
                and classification.confidence
                >= self.plugin.detail_confidence_threshold
            )
            evaluations.append(
                DiscoveryEvaluation(
                    url=current_url,
                    label=label,
                    page_type=classification.page_type,
                    confidence=classification.confidence,
                    signals=classification.matched_signals,
                    accepted=is_disease,
                )
            )
            if is_disease:
                item = await self._make_item(page, current_url)
                if item.item_id not in accepted:
                    accepted[item.item_id] = item
                    await self.items.upsert_discovered(job_id, [item])
            await progress(
                len(accepted),
                len(evaluated_urls),
                len(queue),
                classification.page_type.value,
            )
            if classification.page_type in {
                PageType.DISEASE_DETAIL,
                PageType.DISEASE_LIST,
                PageType.HOME_OR_MENU,
                PageType.UNKNOWN,
            }:
                await enqueue_from_current_page()

        await evaluate_current(None)
        stopped_reason = "candidate_queue_exhausted"
        while queue and len(accepted) < self.policy.max_items:
            if len(evaluated_urls) >= self.policy.max_pages:
                stopped_reason = "max_pages"
                break
            _, _, candidate = heapq.heappop(queue)
            candidate_url = str(candidate.url)
            queued_urls.discard(candidate_url)
            if candidate_url in evaluated_urls:
                continue
            try:
                await self.plugin.navigate_to_candidate(
                    page,
                    self._as_navigation_candidate(candidate),
                )
                await self.plugin.dismiss_known_popups(page)
                await evaluate_current(candidate.label)
            except CrawlerError as exc:
                if exc.code in {
                    ErrorCode.AUTH_SESSION_EXPIRED,
                    ErrorCode.AUTH_MFA_OR_CAPTCHA,
                }:
                    raise
                evaluated_urls.add(candidate_url)
                evaluations.append(
                    DiscoveryEvaluation(
                        url=candidate.url,
                        label=candidate.label,
                        page_type=PageType.UNKNOWN,
                        confidence=0,
                        signals=(f"navigation_error:{exc.code.value}",),
                        accepted=False,
                    )
                )
                await progress(
                    len(accepted),
                    len(evaluated_urls),
                    len(queue),
                    "navigation_error",
                )

        if len(accepted) >= self.policy.max_items:
            stopped_reason = "max_items"

        persisted = await self.items.list_for_job(job_id)
        result = IntelligentDiscoveryResult(
            items=tuple(persisted),
            pages_evaluated=len(evaluated_urls),
            candidates_seen=len(evaluated_urls) + len(queued_urls),
            stopped_reason=stopped_reason,
            evaluations=tuple(evaluations),
        )
        self._export(job_id, result)
        return result

    async def _make_item(self, page: Page, current_url: str) -> DiscoveredItem:
        title = "Disease"
        for selector in self.plugin.content_title_selectors():
            locator = page.locator(selector)
            if not await locator.count():
                continue
            value = " ".join((await locator.first.inner_text()).split())
            if value:
                title = value
                break
        return DiscoveredItem(
            item_id=build_item_id(self.plugin.name, current_url),
            source_url=current_url,
            canonical_url=current_url,
            title_hint=title,
            discovery_page=current_url,
        )

    def _as_navigation_candidate(
        self,
        candidate: DiscoveryCandidate,
    ) -> NavigationCandidate:
        return NavigationCandidate(
            key=str(candidate.url),
            action="goto",
            target=str(candidate.url),
            label=candidate.label,
            url=candidate.url,
        )

    def _export(
        self,
        job_id: str,
        result: IntelligentDiscoveryResult,
    ) -> None:
        job_output = self.output_root / "jobs" / job_id
        job_output.mkdir(parents=True, exist_ok=True)
        self._atomic_json(
            job_output / "ai-discovery.json",
            {
                "job_id": job_id,
                "mode": "hybrid_semantic_graph",
                **result.model_dump(mode="json"),
            },
        )
        self._atomic_json(
            job_output / "disease-list.json",
            {
                "job_id": job_id,
                "count": len(result.items),
                "items": [
                    item.model_dump(mode="json") for item in result.items
                ],
            },
        )

    def _atomic_json(self, target: Path, payload: object) -> None:
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=target.parent,
                prefix=f".{target.stem}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                json.dump(payload, temporary, ensure_ascii=False, indent=2)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, target)
        except Exception:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise
