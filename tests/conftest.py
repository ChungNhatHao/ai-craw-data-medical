from pathlib import Path

import pytest

from app.core.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        database_path=tmp_path / "state" / "crawler.db",
        migrations_path=Path("migrations"),
        output_root=tmp_path / "output",
        session_root=tmp_path / "sessions",
        agentic_discovery_enabled=False,
        ai_normalization_enabled=False,
    )
