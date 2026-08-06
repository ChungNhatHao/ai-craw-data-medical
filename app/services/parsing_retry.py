import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol

from app.core.errors import CrawlerError, ErrorCode
from app.models.discovery import DiscoveredItem
from app.models.disease import ParsedArtifactResult, ParsingPolicy

RETRYABLE_PARSE_ERRORS = frozenset(
    {
        ErrorCode.PARSE_TIMEOUT,
        ErrorCode.GEMINI_TIMEOUT,
        ErrorCode.GEMINI_RATE_LIMITED,
        ErrorCode.GEMINI_UNAVAILABLE,
    }
)


class ParsingService(Protocol):
    async def run(
        self,
        *,
        job_id: str,
        item: DiscoveredItem,
    ) -> ParsedArtifactResult: ...


class RetryingAgenticParsingService:
    """Retry transient Gemini parsing failures, then use grounded rules."""

    def __init__(
        self,
        *,
        agentic: ParsingService,
        fallback: ParsingService,
        policy: ParsingPolicy,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.agentic = agentic
        self.fallback = fallback
        self.policy = policy
        self.sleeper = sleeper

    async def run(
        self,
        *,
        job_id: str,
        item: DiscoveredItem,
    ) -> ParsedArtifactResult:
        for attempt in range(1, self.policy.max_attempts + 1):
            try:
                return await self.agentic.run(job_id=job_id, item=item)
            except CrawlerError as exc:
                if exc.code not in RETRYABLE_PARSE_ERRORS:
                    raise
                if attempt >= self.policy.max_attempts:
                    return await self.fallback.run(job_id=job_id, item=item)
                await self.sleeper(self._retry_delay(attempt))
        raise AssertionError("Parsing retry loop exited unexpectedly")

    def _retry_delay(self, attempt: int) -> float:
        return min(
            self.policy.retry_base_seconds * (2.0 ** (attempt - 1)),
            self.policy.retry_max_seconds,
        )
