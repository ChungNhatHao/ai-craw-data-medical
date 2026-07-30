import asyncio
from pathlib import Path

import pytest

from app.models.navigation import PageType
from app.plugins.genre_manuals.plugin import GenreManualsPlugin
from tests.support.fixture_page import FixturePage

FIXTURES = Path("tests/fixtures/genre_manuals")
BASE_URL = "https://www.genre-manuals.com/sites/CLUE/home.html"


def make_plugin() -> GenreManualsPlugin:
    return GenreManualsPlugin(
        base_url=BASE_URL,
        navigation_timeout_ms=1_000,
        selector_timeout_ms=500,
        detail_confidence_threshold=0.80,
        minimum_detail_chars=250,
    )


@pytest.mark.parametrize(
    ("fixture", "url", "expected_type"),
    [
        ("login.html", BASE_URL, PageType.LOGIN),
        (
            "blocked.html",
            "https://www.genre-manuals.com/access-check",
            PageType.BLOCKED_OR_CAPTCHA,
        ),
        (
            "home_menu.html",
            "https://www.genre-manuals.com/sites/CLUE/dashboard.html",
            PageType.HOME_OR_MENU,
        ),
        (
            "disease_list.html",
            "https://www.genre-manuals.com/sites/CLUE/home/medical.html",
            PageType.DISEASE_LIST,
        ),
        (
            "disease_detail.html",
            "https://www.genre-manuals.com/en_med_asthma.htm",
            PageType.DISEASE_DETAIL,
        ),
        (
            "unknown.html",
            "https://www.genre-manuals.com/temporary.html",
            PageType.UNKNOWN,
        ),
    ],
)
def test_page_classifier(
    fixture: str,
    url: str,
    expected_type: PageType,
) -> None:
    async def scenario() -> None:
        page = FixturePage(FIXTURES, fixture, initial_url=url)

        classification = await make_plugin().classify_page(page)  # type: ignore[arg-type]

        assert classification.page_type is expected_type
        assert 0 <= classification.confidence <= 1
        assert len(classification.fingerprint) == 64
        assert classification.matched_signals

    asyncio.run(scenario())


def test_detail_page_requires_combined_signals() -> None:
    async def scenario() -> None:
        page = FixturePage(
            FIXTURES,
            "unknown.html",
            initial_url="https://www.genre-manuals.com/en_med_unknown.htm",
        )

        classification = await make_plugin().classify_page(page)  # type: ignore[arg-type]

        assert classification.page_type is PageType.UNKNOWN
        assert classification.confidence < 0.80

    asyncio.run(scenario())


def test_candidate_selection_skips_visited_url() -> None:
    async def scenario() -> None:
        page = FixturePage(
            FIXTURES,
            "disease_list.html",
            initial_url="https://www.genre-manuals.com/sites/CLUE/home/medical.html",
        )
        visited = frozenset({"https://www.genre-manuals.com/en_med_asthma.htm"})

        candidate = await make_plugin().find_next_content_candidate(  # type: ignore[arg-type]
            page,
            visited,
        )

        assert candidate is not None
        assert candidate.key not in visited
        assert candidate.action == "goto"

    asyncio.run(scenario())


def test_known_popup_is_dismissed_before_classification() -> None:
    async def scenario() -> None:
        page = FixturePage(
            FIXTURES,
            "popup_home.html",
            initial_url="https://www.genre-manuals.com/sites/CLUE/dashboard.html",
        )
        plugin = make_plugin()

        dismissed = await plugin.dismiss_known_popups(page)  # type: ignore[arg-type]
        classification = await plugin.classify_page(page)  # type: ignore[arg-type]

        assert dismissed == 1
        assert await page.locator("button[aria-label='Close']").count() == 0
        assert classification.page_type is PageType.HOME_OR_MENU

    asyncio.run(scenario())


def test_screenshot_masks_entire_account_region() -> None:
    async def scenario() -> None:
        page = FixturePage(
            FIXTURES,
            "detail_sensitive_header.html",
            initial_url="https://www.genre-manuals.com/en_fixture_disease.htm",
        )

        masks = await make_plugin().screenshot_masks(page)  # type: ignore[arg-type]

        assert len(masks) == 1
        assert await masks[0].count() == 1
        assert masks[0].selector == "#genre-shortcuts"

    asyncio.run(scenario())
