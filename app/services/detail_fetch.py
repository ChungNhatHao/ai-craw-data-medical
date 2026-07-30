import asyncio
from collections.abc import Awaitable, Callable
from typing import cast

from playwright.async_api import Page

from app.core.errors import CrawlerError, ErrorCode
from app.models.artifacts import RawFetchPolicy, RawFetchResult
from app.models.discovery import DiscoveredItem
from app.models.navigation import NavigationCandidate, PageType
from app.plugins.base import SitePlugin
from app.repositories.attempts import AttemptRepository
from app.repositories.items import ItemRepository
from app.storage.artifacts import ArtifactStore

RETRYABLE_FETCH_ERRORS = frozenset(
    {
        ErrorCode.NETWORK_TIMEOUT,
        ErrorCode.NAVIGATION_FAILED,
        ErrorCode.CONTENT_EMPTY,
        ErrorCode.STORAGE_WRITE,
    }
)


class DetailFetchService:
    def __init__(
        self,
        *,
        plugin: SitePlugin,
        items: ItemRepository,
        attempts: AttemptRepository,
        artifacts: ArtifactStore,
        policy: RawFetchPolicy,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.plugin = plugin
        self.items = items
        self.attempts = attempts
        self.artifacts = artifacts
        self.policy = policy
        self.sleeper = sleeper

    async def run(
        self,
        page: Page,
        *,
        job_id: str,
        item: DiscoveredItem,
    ) -> RawFetchResult:
        recovered = self.artifacts.load_valid_raw(job_id, item)
        if recovered is not None:
            manifest, artifact_dir = recovered
            await self.items.mark_fetched(job_id, item.item_id, artifact_dir)
            checkpoint = await self.items.get_checkpoint(job_id, item.item_id)
            return RawFetchResult(
                job_id=job_id,
                item_id=item.item_id,
                artifact_dir=artifact_dir,
                manifest=manifest,
                attempt_count=checkpoint.attempt_count if checkpoint else 0,
                reused_artifacts=True,
            )

        last_error: CrawlerError | None = None
        for policy_attempt in range(1, self.policy.max_attempts + 1):
            attempt_no = await self.items.mark_fetching(job_id, item.item_id)
            attempt_id = await self.attempts.start(
                job_id,
                item.item_id,
                attempt_no,
                "fetch_raw",
            )
            try:
                result = await self._fetch_once(
                    page,
                    job_id=job_id,
                    item=item,
                    attempt_count=attempt_no,
                )
            except CrawlerError as exc:
                last_error = exc
                await self.attempts.finish(
                    attempt_id,
                    result="failure",
                    error_code=exc.code.value,
                    error_message=str(exc),
                )
                should_retry = (
                    exc.code in RETRYABLE_FETCH_ERRORS
                    and policy_attempt < self.policy.max_attempts
                )
                if should_retry:
                    await self.sleeper(self._retry_delay(policy_attempt))
                    continue
                await self.items.mark_fetch_failed(
                    job_id,
                    item.item_id,
                    exc.code.value,
                )
                raise
            except Exception as exc:
                unexpected = CrawlerError(
                    ErrorCode.UNEXPECTED,
                    "Unexpected failure while fetching disease detail",
                )
                await self.attempts.finish(
                    attempt_id,
                    result="failure",
                    error_code=unexpected.code.value,
                    error_message=str(unexpected),
                )
                await self.items.mark_fetch_failed(
                    job_id,
                    item.item_id,
                    unexpected.code.value,
                )
                raise unexpected from exc
            else:
                await self.attempts.finish(attempt_id, result="success")
                return result

        if last_error is None:
            raise CrawlerError(ErrorCode.UNEXPECTED, "Fetch attempt loop did not run")
        raise last_error

    async def _fetch_once(
        self,
        page: Page,
        *,
        job_id: str,
        item: DiscoveredItem,
        attempt_count: int,
    ) -> RawFetchResult:
        canonical_url = str(item.canonical_url)
        await self.plugin.navigate_to_candidate(
            page,
            NavigationCandidate(
                key=canonical_url,
                action="goto",
                target=canonical_url,
                label=item.title_hint,
                url=item.canonical_url,
            ),
        )
        await self.plugin.dismiss_known_popups(page)
        classification = await self.plugin.classify_page(page)
        self._require_detail(classification.page_type)
        await self.plugin.wait_for_detail_content(page)
        stable_classification = await self.plugin.classify_page(page)
        self._require_detail(stable_classification.page_type)

        html = await page.content()
        if not html.strip():
            raise CrawlerError(ErrorCode.CONTENT_EMPTY, "Disease page HTML is empty")
        tabs = await self.plugin.capture_detail_tabs(page)
        screenshot = None
        if self.policy.capture_screenshot:
            masks = await self.plugin.screenshot_masks(page)
            screenshot = await page.screenshot(
                type="png",
                full_page=True,
                mask=masks,
                mask_color="#20252b",
            )
        manifest, artifact_dir = self.artifacts.persist_raw(
            job_id=job_id,
            plugin=self.plugin.name,
            item=item,
            html=html,
            screenshot=screenshot,
            confidence=stable_classification.confidence,
            tabs=tabs,
        )
        await self.items.mark_fetched(job_id, item.item_id, artifact_dir)
        return RawFetchResult(
            job_id=job_id,
            item_id=item.item_id,
            artifact_dir=artifact_dir,
            manifest=manifest,
            attempt_count=attempt_count,
        )

    def _require_detail(self, page_type: PageType) -> None:
        if page_type is PageType.LOGIN:
            raise CrawlerError(
                ErrorCode.AUTH_SESSION_EXPIRED,
                "Detail navigation returned to login",
            )
        if page_type is PageType.BLOCKED_OR_CAPTCHA:
            raise CrawlerError(
                ErrorCode.AUTH_MFA_OR_CAPTCHA,
                "Detail navigation encountered a blocked or CAPTCHA page",
            )
        if page_type is not PageType.DISEASE_DETAIL:
            raise CrawlerError(
                ErrorCode.PAGE_TYPE_UNKNOWN,
                "Raw capture requires a confirmed disease detail page",
            )

    def _retry_delay(self, attempt: int) -> float:
        return cast(
            float,
            min(
                self.policy.base_delay_seconds * (2 ** (attempt - 1)),
                self.policy.max_delay_seconds,
            ),
        )
