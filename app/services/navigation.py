from collections import Counter
from typing import NoReturn

from playwright.async_api import Page

from app.core.errors import CrawlerError, ErrorCode
from app.models.navigation import (
    NavigationPolicy,
    NavigationResult,
    PageClassification,
    PageType,
)
from app.plugins.base import SitePlugin


class NavigationDetectionLoop:
    """Navigate until a page is positively classified as disease detail."""

    def __init__(self, plugin: SitePlugin, policy: NavigationPolicy) -> None:
        self.plugin = plugin
        self.policy = policy

    async def locate_disease_detail(self, page: Page) -> NavigationResult:
        fingerprints: Counter[str] = Counter()
        visited_candidates: set[str] = set()
        no_progress_count = 0
        last_fingerprint: str | None = None
        last_classification: PageClassification | None = None

        for hop_count in range(1, self.policy.max_hops + 1):
            await self.plugin.dismiss_known_popups(page)
            classification = await self.plugin.classify_page(page)
            last_classification = classification
            fingerprints[classification.fingerprint] += 1

            if classification.page_type is PageType.DISEASE_DETAIL:
                return NavigationResult(
                    classification=classification,
                    hop_count=hop_count,
                    visited_candidates=tuple(sorted(visited_candidates)),
                )
            if classification.page_type is PageType.BLOCKED_OR_CAPTCHA:
                raise CrawlerError(
                    ErrorCode.AUTH_MFA_OR_CAPTCHA,
                    "Navigation encountered a blocked or CAPTCHA page",
                )
            if classification.page_type is PageType.LOGIN:
                raise CrawlerError(
                    ErrorCode.AUTH_SESSION_EXPIRED,
                    "Navigation returned to the login page",
                )
            if (
                fingerprints[classification.fingerprint]
                >= self.policy.max_same_fingerprint
            ):
                self._raise_exhausted("Repeated page fingerprint")

            candidate = await self.plugin.find_next_content_candidate(
                page,
                frozenset(visited_candidates),
            )
            if candidate is None:
                no_progress_count = (
                    no_progress_count + 1
                    if last_fingerprint == classification.fingerprint
                    else 1
                )
            else:
                if candidate.key in visited_candidates:
                    no_progress_count += 1
                else:
                    visited_candidates.add(candidate.key)
                    await self.plugin.navigate_to_candidate(page, candidate)
                    no_progress_count = 0

            last_fingerprint = classification.fingerprint

            if no_progress_count >= self.policy.max_no_progress:
                self._raise_exhausted("Navigation made no progress")

        if last_classification is None:
            self._raise_exhausted("No page could be classified")
        self._raise_exhausted(
            f"Maximum navigation hops reached from {last_classification.page_type.value}"
        )

    def _raise_exhausted(self, reason: str) -> NoReturn:
        raise CrawlerError(
            ErrorCode.NAVIGATION_LOOP_EXHAUSTED,
            reason,
        )
