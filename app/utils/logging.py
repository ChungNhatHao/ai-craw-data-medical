from __future__ import annotations

import sys
from collections.abc import Callable
from typing import TYPE_CHECKING

from loguru import logger

from app.core.config import Settings

if TYPE_CHECKING:
    from loguru import Record


def redact_text(text: str, secrets: frozenset[str]) -> str:
    redacted = text
    for secret in secrets:
        redacted = redacted.replace(secret, "[REDACTED]")
    return redacted


def build_secret_filter(
    secrets: frozenset[str],
) -> Callable[[Record], bool]:
    sensitive_keys = {"password", "cookie", "authorization", "token", "secret"}

    def redact(record: Record) -> bool:
        record["message"] = redact_text(str(record["message"]), secrets)
        extra = record.get("extra", {})
        for key in list(extra):
            if key.lower() in sensitive_keys:
                extra[key] = "[REDACTED]"
            elif isinstance(extra[key], str):
                extra[key] = redact_text(extra[key], secrets)
        return True

    return redact


def configure_logging(settings: Settings) -> None:
    logger.remove()
    logger.add(
        sys.stderr,
        level=settings.log_level.upper(),
        serialize=settings.log_json,
        backtrace=settings.app_env == "local",
        diagnose=False,
        filter=build_secret_filter(settings.secret_values()),
    )
