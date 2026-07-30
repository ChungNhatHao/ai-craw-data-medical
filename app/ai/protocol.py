from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict


class ProviderErrorKind(StrEnum):
    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    INVALID_REQUEST = "invalid_request"


class GeminiTransportError(Exception):
    def __init__(
        self,
        kind: ProviderErrorKind,
        *,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(kind.value)
        self.kind = kind
        self.retry_after_seconds = retry_after_seconds


class GeminiUsage(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True, slots=True)
class GeminiTransportResponse:
    parsed: Any
    usage: GeminiUsage = GeminiUsage()
    model_version: str | None = None


class GeminiTransport(Protocol):
    async def generate_structured(
        self,
        *,
        model: str,
        prompt: str,
        response_schema: type[BaseModel],
        temperature: float,
    ) -> GeminiTransportResponse: ...


class GeminiCallResult[ResponseT: BaseModel](BaseModel):
    model_config = ConfigDict(frozen=True)

    value: ResponseT
    usage: GeminiUsage = GeminiUsage()
    model_id: str
    model_version: str | None = None
    attempts: int
    latency_ms: int
