import asyncio
from pathlib import Path

import pytest

from app.core.errors import CrawlerError, ErrorCode
from app.models.navigation import NavigationPolicy, PageType
from app.plugins.genre_manuals.plugin import GenreManualsPlugin
from app.services.navigation import NavigationDetectionLoop
from tests.support.fixture_page import FixturePage

FIXTURES = Path("tests/fixtures/genre_manuals")
BASE_URL = "https://www.genre-manuals.com/sites/CLUE/home.html"
MEDICAL_URL = "https://www.genre-manuals.com/sites/CLUE/home/medical.html"
ASTHMA_URL = "https://www.genre-manuals.com/en_med_asthma.htm"


def make_plugin() -> GenreManualsPlugin:
    return GenreManualsPlugin(
        base_url=BASE_URL,
        navigation_timeout_ms=1_000,
        selector_timeout_ms=500,
        detail_confidence_threshold=0.80,
        minimum_detail_chars=250,
    )


def make_loop(
    *,
    max_hops: int = 12,
    max_same_fingerprint: int = 3,
    max_no_progress: int = 2,
) -> NavigationDetectionLoop:
    return NavigationDetectionLoop(
        make_plugin(),
        NavigationPolicy(
            max_hops=max_hops,
            max_same_fingerprint=max_same_fingerprint,
            max_no_progress=max_no_progress,
        ),
    )


def test_navigation_loops_from_home_to_list_to_confirmed_detail() -> None:
    async def scenario() -> None:
        page = FixturePage(
            FIXTURES,
            "home_menu.html",
            initial_url=BASE_URL,
            route_fixtures={
                MEDICAL_URL: "disease_list.html",
                ASTHMA_URL: "disease_detail.html",
            },
        )

        result = await make_loop().locate_disease_detail(page)  # type: ignore[arg-type]

        assert result.classification.page_type is PageType.DISEASE_DETAIL
        assert result.hop_count == 3
        assert result.visited_candidates == (ASTHMA_URL, MEDICAL_URL)
        assert page.url == ASTHMA_URL

    asyncio.run(scenario())


def test_unknown_page_stops_at_no_progress_guard() -> None:
    async def scenario() -> None:
        page = FixturePage(
            FIXTURES,
            "unknown.html",
            initial_url="https://www.genre-manuals.com/temporary.html",
        )

        with pytest.raises(CrawlerError) as captured:
            await make_loop(max_no_progress=2).locate_disease_detail(  # type: ignore[arg-type]
                page
            )

        assert captured.value.code is ErrorCode.NAVIGATION_LOOP_EXHAUSTED
        assert "no progress" in str(captured.value).lower()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("fixture", "expected_error"),
    [
        ("login.html", ErrorCode.AUTH_SESSION_EXPIRED),
        ("blocked.html", ErrorCode.AUTH_MFA_OR_CAPTCHA),
    ],
)
def test_login_and_blocked_pages_leave_navigation_loop(
    fixture: str,
    expected_error: ErrorCode,
) -> None:
    async def scenario() -> None:
        page = FixturePage(FIXTURES, fixture, initial_url=BASE_URL)

        with pytest.raises(CrawlerError) as captured:
            await make_loop().locate_disease_detail(page)  # type: ignore[arg-type]

        assert captured.value.code is expected_error

    asyncio.run(scenario())

