import json
import os
import tempfile
from pathlib import Path
from typing import cast

from playwright.async_api import StorageState

from app.core.errors import CrawlerError, ErrorCode


class SessionStore:
    """Persist Playwright storage state without exposing it through logs."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> StorageState | None:
        if not self.path.exists():
            return None
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CrawlerError(
                ErrorCode.SESSION_STATE_INVALID,
                "Stored browser session is unreadable or invalid",
            ) from exc
        if not isinstance(payload, dict):
            raise CrawlerError(
                ErrorCode.SESSION_STATE_INVALID,
                "Stored browser session must be a JSON object",
            )
        cookies = payload.get("cookies")
        origins = payload.get("origins")
        if not isinstance(cookies, list) or not isinstance(origins, list):
            raise CrawlerError(
                ErrorCode.SESSION_STATE_INVALID,
                "Stored browser session has an unsupported shape",
            )
        return cast(StorageState, payload)

    def save(self, state: StorageState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                json.dump(state, temporary, ensure_ascii=False, separators=(",", ":"))
                temporary.flush()
                os.fsync(temporary.fileno())
            temporary_path.chmod(0o600)
            os.replace(temporary_path, self.path)
        except (OSError, TypeError, ValueError) as exc:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise CrawlerError(
                ErrorCode.STORAGE_WRITE,
                "Could not persist browser session",
            ) from exc
