import pytest

from app.core.config import Settings


def test_credentials_are_required_and_redacted() -> None:
    settings = Settings(
        genre_manuals_username="example-user",
        genre_manuals_password="example-password",
    )

    credentials = settings.require_genre_manuals_credentials()

    assert "example-password" not in repr(credentials)
    assert "**********" in repr(credentials)


def test_missing_credentials_fail_without_echoing_values() -> None:
    settings = Settings(
        _env_file=None,
        genre_manuals_username=None,
        genre_manuals_password=None,
    )

    with pytest.raises(ValueError, match="must be set"):
        settings.require_genre_manuals_credentials()
