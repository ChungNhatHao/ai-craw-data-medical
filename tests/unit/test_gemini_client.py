import asyncio
from collections.abc import Awaitable, Callable

import pytest
from pydantic import BaseModel

from app.ai.client import GeminiClient
from app.ai.protocol import (
    GeminiTransportError,
    GeminiTransportResponse,
    GeminiUsage,
    ProviderErrorKind,
)
from app.core.errors import CrawlerError, ErrorCode


class Answer(BaseModel):
    disease_name: str
    confidence: float


Outcome = GeminiTransportResponse | Exception | Callable[[], Awaitable[None]]


class FakeTransport:
    def __init__(self, outcomes: list[Outcome]) -> None:
        self.outcomes = outcomes
        self.calls = 0

    async def generate_structured(
        self,
        *,
        model: str,
        prompt: str,
        response_schema: type[BaseModel],
        temperature: float,
    ) -> GeminiTransportResponse:
        del model, prompt, response_schema, temperature
        outcome = self.outcomes[self.calls]
        self.calls += 1
        if isinstance(outcome, Exception):
            raise outcome
        if callable(outcome):
            await outcome()
            raise AssertionError("blocking outcome unexpectedly completed")
        return outcome


def test_structured_success_returns_validation_and_usage_metadata() -> None:
    async def scenario() -> None:
        transport = FakeTransport(
            [
                GeminiTransportResponse(
                    parsed={"disease_name": "Down syndrome", "confidence": 0.97},
                    usage=GeminiUsage(
                        input_tokens=12,
                        output_tokens=8,
                        total_tokens=20,
                    ),
                    model_version="gemini-test-001",
                )
            ]
        )
        client = GeminiClient(transport=transport, max_retries=0)

        result = await client.generate_structured(
            model="gemini-test",
            prompt="Return a grounded decision",
            response_schema=Answer,
        )

        assert result.value.disease_name == "Down syndrome"
        assert result.usage.total_tokens == 20
        assert result.model_version == "gemini-test-001"
        assert result.attempts == 1

    asyncio.run(scenario())


def test_timeout_is_retried_then_raised_with_safe_message() -> None:
    async def block() -> None:
        await asyncio.Event().wait()

    async def scenario() -> None:
        transport = FakeTransport([block, block])
        delays: list[float] = []

        async def no_sleep(delay: float) -> None:
            delays.append(delay)

        client = GeminiClient(
            transport=transport,
            timeout_seconds=0.001,
            max_retries=1,
            retry_base_seconds=0.25,
            sleeper=no_sleep,
        )

        with pytest.raises(CrawlerError) as captured:
            await client.generate_structured(
                model="gemini-test",
                prompt="content",
                response_schema=Answer,
            )

        assert captured.value.code is ErrorCode.GEMINI_TIMEOUT
        assert transport.calls == 2
        assert delays == [0.25]

    asyncio.run(scenario())


def test_rate_limit_honors_retry_after_and_succeeds() -> None:
    async def scenario() -> None:
        transport = FakeTransport(
            [
                GeminiTransportError(
                    ProviderErrorKind.RATE_LIMIT,
                    retry_after_seconds=3.5,
                ),
                GeminiTransportResponse(
                    parsed={"disease_name": "Turner syndrome", "confidence": 0.9}
                ),
            ]
        )
        delays: list[float] = []

        async def no_sleep(delay: float) -> None:
            delays.append(delay)

        client = GeminiClient(
            transport=transport,
            max_retries=1,
            sleeper=no_sleep,
        )
        result = await client.generate_structured(
            model="gemini-test",
            prompt="content",
            response_schema=Answer,
        )

        assert result.attempts == 2
        assert delays == [3.5]

    asyncio.run(scenario())


def test_invalid_structured_response_has_stable_error_without_payload() -> None:
    async def scenario() -> None:
        secret = "do-not-leak-api-key"
        transport = FakeTransport(
            [
                GeminiTransportResponse(
                    parsed={"disease_name": secret, "confidence": "not-a-number"}
                )
            ]
        )
        client = GeminiClient(transport=transport)

        with pytest.raises(CrawlerError) as captured:
            await client.generate_structured(
                model="gemini-test",
                prompt="content",
                response_schema=Answer,
            )

        assert captured.value.code is ErrorCode.GEMINI_OUTPUT_INVALID
        assert secret not in str(captured.value)
        assert transport.calls == 1

    asyncio.run(scenario())


def test_provider_auth_error_does_not_echo_provider_message_or_retry() -> None:
    async def scenario() -> None:
        secret = "AIza-secret-value"
        provider_error = GeminiTransportError(ProviderErrorKind.AUTH)
        provider_error.add_note(secret)
        transport = FakeTransport([provider_error])
        client = GeminiClient(transport=transport, max_retries=3)

        with pytest.raises(CrawlerError) as captured:
            await client.generate_structured(
                model="gemini-test",
                prompt="content",
                response_schema=Answer,
            )

        assert captured.value.code is ErrorCode.GEMINI_AUTH_FAILED
        assert secret not in str(captured.value)
        assert transport.calls == 1

    asyncio.run(scenario())
