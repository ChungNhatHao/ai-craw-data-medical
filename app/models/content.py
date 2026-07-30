import re
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

SHA256_PATTERN = r"^[0-9a-f]{64}$"
HTML_MARKER = re.compile(
    r"<!doctype|<\s*/?\s*(?:html|head|body|script|style|form|iframe|"
    r"input|button|nav|footer|header|aside|article|div|span|p|h[1-6]|"
    r"table|tr|t[dh]|ul|ol|li|a)\b",
    re.IGNORECASE,
)
FORBIDDEN_CONTENT_KEYS = frozenset(
    {
        "raw_html",
        "html",
        "content_html",
        "clean_html",
        "dom",
        "page_source",
    }
)


class UnsafeContentPayload(ValueError):
    """Raised before a content payload containing HTML can reach an AI client."""


class NormalizationInput(BaseModel):
    """HTML-free input contract for disease extraction/normalization agents."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_url: str = Field(min_length=1)
    content_hash: str = Field(pattern=SHA256_PATTERN)
    title: str | None = None
    plain_text: str = Field(min_length=1)

    @field_validator("title", "plain_text")
    @classmethod
    def reject_html(cls, value: str | None) -> str | None:
        if value is not None and HTML_MARKER.search(value):
            raise ValueError("AI content input must not contain HTML markup")
        return value

    def to_agent_payload(self) -> dict[str, str | None]:
        payload = self.model_dump(mode="json")
        assert_safe_content_payload(payload)
        return payload


def assert_safe_content_payload(payload: Mapping[str, Any]) -> None:
    """Fail closed when raw/clean HTML is accidentally added to an AI request."""

    _assert_safe_value(payload, path="payload")


def _assert_safe_value(value: Any, *, path: str) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized_key = str(key).strip().casefold()
            if normalized_key in FORBIDDEN_CONTENT_KEYS:
                raise UnsafeContentPayload(
                    f"Forbidden HTML field at {path}.{key}"
                )
            _assert_safe_value(nested, path=f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _assert_safe_value(nested, path=f"{path}[{index}]")
        return
    if isinstance(value, str) and HTML_MARKER.search(value):
        raise UnsafeContentPayload(f"HTML markup found at {path}")
