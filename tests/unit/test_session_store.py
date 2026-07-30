import json
import stat

import pytest

from app.browser.session import SessionStore
from app.core.errors import CrawlerError, ErrorCode


def test_session_store_round_trip_with_restricted_permissions(tmp_path) -> None:
    path = tmp_path / "sessions" / "genre_manuals.json"
    store = SessionStore(path)
    state = {
        "cookies": [{"name": "session", "value": "test-only"}],
        "origins": [],
    }

    store.save(state)

    assert store.load() == state
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not list(path.parent.glob("*.tmp"))


def test_session_store_rejects_corrupted_json(tmp_path) -> None:
    path = tmp_path / "session.json"
    path.write_text("{invalid", encoding="utf-8")

    with pytest.raises(CrawlerError) as captured:
        SessionStore(path).load()

    assert captured.value.code is ErrorCode.SESSION_STATE_INVALID


def test_session_store_writes_valid_compact_json(tmp_path) -> None:
    path = tmp_path / "session.json"
    SessionStore(path).save({"cookies": [], "origins": []})

    assert json.loads(path.read_text(encoding="utf-8")) == {
        "cookies": [],
        "origins": [],
    }

