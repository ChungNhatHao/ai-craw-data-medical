import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from google import genai
from google.genai import errors, types
from pydantic import BaseModel, SecretStr, ValidationError

from app.ai.protocol import (
    GeminiCallResult,
    GeminiTransport,
    GeminiTransportError,
    GeminiTransportResponse,
    GeminiUsage,
    ProviderErrorKind,
)
from app.core.errors import CrawlerError, ErrorCode

Sleeper = Callable[[float], Awaitable[None]]


class GoogleGenAITransport:
    """Thin adapter around the official async Google Gen AI SDK."""

    def __init__(
        self,
        *,
        api_key: SecretStr,
        timeout_seconds: float,
    ) -> None:
        self._client = genai.Client(
            api_key=api_key.get_secret_value(),
            http_options=types.HttpOptions(
                api_version="v1",
                timeout=max(1, round(timeout_seconds * 1_000)),
            ),
        )

    async def generate_structured(
        self,
        *,
        model: str,
        prompt: str,
        response_schema: type[BaseModel],
        temperature: float,
    ) -> GeminiTransportResponse:
        try:
            config: dict[str, object] = {
                "response_mime_type": "application/json",
                # The Schema protobuf used by response_schema rejects standard
                # JSON Schema keywords emitted by strict Pydantic models (for
                # example additionalProperties). response_json_schema accepts
                # the complete contract and still returns parsed JSON.
                "response_json_schema": response_schema.model_json_schema(),
            }
            if not model.startswith("gemini-3"):
                config["temperature"] = temperature
            response = await self._client.aio.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(**config),
            )
        except errors.APIError as exc:
            raise _provider_error(exc) from None
        except TimeoutError:
            raise GeminiTransportError(ProviderErrorKind.TIMEOUT) from None

        usage = response.usage_metadata
        return GeminiTransportResponse(
            parsed=response.parsed,
            usage=GeminiUsage(
                input_tokens=(usage.prompt_token_count or 0) if usage else 0,
                output_tokens=(usage.candidates_token_count or 0) if usage else 0,
                total_tokens=(usage.total_token_count or 0) if usage else 0,
            ),
            model_version=response.model_version,
        )


class GeminiClient:
    """Policy wrapper providing validation, timeout, retry, and safe errors."""

    def __init__(
        self,
        *,
        transport: GeminiTransport,
        timeout_seconds: float = 30,
        max_retries: int = 2,
        retry_base_seconds: float = 1,
        retry_max_seconds: float = 20,
        sleeper: Sleeper = asyncio.sleep,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        if retry_base_seconds < 0 or retry_max_seconds < 0:
            raise ValueError("retry delays cannot be negative")
        self._transport = transport
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._retry_base_seconds = retry_base_seconds
        self._retry_max_seconds = retry_max_seconds
        self._sleeper = sleeper

    async def generate_structured[ResponseT: BaseModel](
        self,
        *,
        model: str,
        prompt: str,
        response_schema: type[ResponseT],
        temperature: float = 0,
    ) -> GeminiCallResult[ResponseT]:
        if not model.strip():
            raise ValueError("model cannot be empty")
        if not prompt.strip():
            raise ValueError("prompt cannot be empty")

        started = time.monotonic()
        attempts = 0
        while True:
            attempts += 1
            try:
                async with asyncio.timeout(self._timeout_seconds):
                    response = await self._transport.generate_structured(
                        model=model,
                        prompt=prompt,
                        response_schema=response_schema,
                        temperature=temperature,
                    )
                value = _validate_response(response.parsed, response_schema)
                return GeminiCallResult[ResponseT](
                    value=value,
                    usage=response.usage,
                    model_id=model,
                    model_version=response.model_version,
                    attempts=attempts,
                    latency_ms=round((time.monotonic() - started) * 1_000),
                )
            except TimeoutError:
                error = CrawlerError(
                    ErrorCode.GEMINI_TIMEOUT,
                    "Gemini request exceeded its configured timeout",
                )
                retry_after = None
            except GeminiTransportError as exc:
                error = _crawler_error(exc.kind)
                retry_after = exc.retry_after_seconds

            if attempts > self._max_retries or error.code not in _RETRYABLE_CODES:
                raise error
            await self._sleeper(
                retry_after if retry_after is not None else self._retry_delay(attempts)
            )

    def _retry_delay(self, attempt: int) -> float:
        return min(
            self._retry_base_seconds * (2.0 ** (attempt - 1)),
            self._retry_max_seconds,
        )


_RETRYABLE_CODES = frozenset(
    {
        ErrorCode.GEMINI_RATE_LIMITED,
        ErrorCode.GEMINI_TIMEOUT,
        ErrorCode.GEMINI_UNAVAILABLE,
    }
)


def _validate_response[ResponseT: BaseModel](
    parsed: Any,
    response_schema: type[ResponseT],
) -> ResponseT:
    try:
        if isinstance(parsed, response_schema):
            return parsed
        return response_schema.model_validate(parsed)
    except (ValidationError, TypeError, ValueError) as exc:
        raise CrawlerError(
            ErrorCode.GEMINI_OUTPUT_INVALID,
            "Gemini structured output failed schema validation",
        ) from exc


def _crawler_error(kind: ProviderErrorKind) -> CrawlerError:
    mapping = {
        ProviderErrorKind.AUTH: (
            ErrorCode.GEMINI_AUTH_FAILED,
            "Gemini authentication failed; check backend configuration",
        ),
        ProviderErrorKind.RATE_LIMIT: (
            ErrorCode.GEMINI_RATE_LIMITED,
            "Gemini request was rate limited",
        ),
        ProviderErrorKind.TIMEOUT: (
            ErrorCode.GEMINI_TIMEOUT,
            "Gemini request timed out",
        ),
        ProviderErrorKind.UNAVAILABLE: (
            ErrorCode.GEMINI_UNAVAILABLE,
            "Gemini service is temporarily unavailable",
        ),
        ProviderErrorKind.INVALID_REQUEST: (
            ErrorCode.GEMINI_OUTPUT_INVALID,
            "Gemini rejected the structured request",
        ),
    }
    code, message = mapping[kind]
    return CrawlerError(code, message)


def _provider_error(error: errors.APIError) -> GeminiTransportError:
    if error.code in {401, 403}:
        kind = ProviderErrorKind.AUTH
    elif error.code == 429:
        kind = ProviderErrorKind.RATE_LIMIT
    elif error.code in {408, 504}:
        kind = ProviderErrorKind.TIMEOUT
    elif error.code >= 500:
        kind = ProviderErrorKind.UNAVAILABLE
    else:
        kind = ProviderErrorKind.INVALID_REQUEST
    return GeminiTransportError(
        kind,
        retry_after_seconds=_retry_after_seconds(error),
    )


def _retry_after_seconds(error: errors.APIError) -> float | None:
    response = error.response
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    value = headers.get("retry-after")
    if value is None:
        return None
    try:
        delay = float(value)
    except (TypeError, ValueError):
        return None
    return max(0, delay)
