import asyncio
from typing import cast

from app.core.errors import CrawlerError, ErrorCode
from app.models.discovery import DiscoveredItem
from app.models.disease import ParsedArtifactResult, ParsingPolicy
from app.services.parsing_retry import RetryingAgenticParsingService


class FakeParsingService:
    def __init__(
        self,
        outcomes: list[ParsedArtifactResult | CrawlerError],
    ) -> None:
        self.outcomes = outcomes
        self.calls = 0

    async def run(
        self,
        *,
        job_id: str,
        item: DiscoveredItem,
    ) -> ParsedArtifactResult:
        del job_id, item
        outcome = self.outcomes[self.calls]
        self.calls += 1
        if isinstance(outcome, CrawlerError):
            raise outcome
        return outcome


ITEM = DiscoveredItem(
    item_id="a" * 64,
    source_url="https://example.test/disease",
    canonical_url="https://example.test/disease",
    discovery_page="https://example.test/list",
)
RESULT = cast(ParsedArtifactResult, object())


def timeout_error() -> CrawlerError:
    return CrawlerError(ErrorCode.PARSE_TIMEOUT, "timed out")


def test_retrying_parser_succeeds_before_fallback() -> None:
    async def scenario() -> None:
        delays: list[float] = []

        async def sleeper(delay: float) -> None:
            delays.append(delay)

        agentic = FakeParsingService(
            [timeout_error(), timeout_error(), RESULT]
        )
        fallback = FakeParsingService([RESULT])
        service = RetryingAgenticParsingService(
            agentic=agentic,
            fallback=fallback,
            policy=ParsingPolicy(
                max_attempts=3,
                retry_base_seconds=2,
                retry_max_seconds=10,
            ),
            sleeper=sleeper,
        )

        result = await service.run(job_id="job", item=ITEM)

        assert result is RESULT
        assert agentic.calls == 3
        assert fallback.calls == 0
        assert delays == [2, 4]

    asyncio.run(scenario())


def test_retrying_parser_falls_back_after_final_timeout() -> None:
    async def scenario() -> None:
        async def sleeper(delay: float) -> None:
            del delay

        agentic = FakeParsingService(
            [timeout_error(), timeout_error(), timeout_error()]
        )
        fallback = FakeParsingService([RESULT])
        service = RetryingAgenticParsingService(
            agentic=agentic,
            fallback=fallback,
            policy=ParsingPolicy(
                max_attempts=3,
                retry_base_seconds=0,
                retry_max_seconds=0,
            ),
            sleeper=sleeper,
        )

        result = await service.run(job_id="job", item=ITEM)

        assert result is RESULT
        assert agentic.calls == 3
        assert fallback.calls == 1

    asyncio.run(scenario())
