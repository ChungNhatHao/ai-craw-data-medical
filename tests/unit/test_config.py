from app.core.config import Settings


def test_ensure_directories(settings: Settings) -> None:
    settings.ensure_directories()

    assert settings.database_path.parent.is_dir()
    assert settings.output_root.is_dir()
    assert settings.session_root.is_dir()


def test_gemini_is_opt_in_and_api_key_is_redacted() -> None:
    settings = Settings(
        _env_file=None,
        gemini_api_key="gemini-secret",
        agentic_discovery_enabled=False,
        ai_normalization_enabled=False,
    )

    assert settings.agentic_discovery_enabled is False
    assert settings.ai_normalization_enabled is False
    assert "gemini-secret" not in repr(settings)
    assert "gemini-secret" in settings.secret_values()
