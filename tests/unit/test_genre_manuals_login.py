from pathlib import Path

import pytest

from app.core.config import Credentials
from app.core.errors import CrawlerError, ErrorCode
from app.plugins.genre_manuals.plugin import GenreManualsPlugin
from tests.support.fixture_page import FixturePage

BASE_URL = "https://www.genre-manuals.com/sites/CLUE/home.html"
FIXTURES = Path("tests/fixtures/genre_manuals")


def make_plugin() -> GenreManualsPlugin:
    return GenreManualsPlugin(
        base_url=BASE_URL,
        navigation_timeout_ms=1_000,
        selector_timeout_ms=500,
    )


def test_login_success_uses_fixture_and_never_exposes_secret() -> None:
    async def scenario() -> None:
        page = FixturePage(FIXTURES, "login.html")
        credentials = Credentials(
            username="valid-user",
            password="valid-password",
        )

        await make_plugin().login(page, credentials)  # type: ignore[arg-type]

        assert await make_plugin().validate_session(page)  # type: ignore[arg-type]
        assert "valid-password" not in repr(credentials)

    import asyncio

    asyncio.run(scenario())


def test_invalid_credentials_are_classified_without_secret_in_error() -> None:
    async def scenario() -> None:
        page = FixturePage(FIXTURES, "login.html")
        credentials = Credentials(username="wrong-user", password="wrong-secret")

        with pytest.raises(CrawlerError) as captured:
            await make_plugin().login(page, credentials)  # type: ignore[arg-type]

        assert captured.value.code is ErrorCode.AUTH_INVALID_CREDENTIALS
        assert "wrong-secret" not in str(captured.value)

    import asyncio

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        ("login.html", False),
        ("authenticated.html", True),
    ],
)
def test_session_validation(fixture: str, expected: bool) -> None:
    async def scenario() -> None:
        page = FixturePage(FIXTURES, fixture)
        assert await make_plugin().validate_session(page) is expected  # type: ignore[arg-type]

    import asyncio

    asyncio.run(scenario())


def test_captcha_requires_operator_action() -> None:
    async def scenario() -> None:
        page = FixturePage(FIXTURES, "captcha.html")
        credentials = Credentials(
            username="valid-user",
            password="valid-password",
        )

        with pytest.raises(CrawlerError) as captured:
            await make_plugin().login(page, credentials)  # type: ignore[arg-type]

        assert captured.value.code is ErrorCode.AUTH_MFA_OR_CAPTCHA

    import asyncio

    asyncio.run(scenario())

