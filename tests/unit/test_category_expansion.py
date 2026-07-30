import asyncio
from typing import Any, cast

from bs4 import BeautifulSoup, Tag
from playwright.async_api import Page

from app.models.navigation import PageClassification, PageType
from app.services.category_expansion import (
    CategoryExpansionPolicy,
    CategoryExpansionService,
    SafeCategorySearchMatcher,
    SearchCandidate,
    is_exact_alias_match,
    is_singular_plural_pair,
    normalize_search_name,
)


def classification(page_type: PageType) -> PageClassification:
    return PageClassification(
        page_type=page_type,
        confidence=1,
        fingerprint=f"{page_type.value:0<12}",
    )


def test_name_normalization_and_plural_pair_are_narrow() -> None:
    assert normalize_search_name("  Cardiac—Arrhythmia! ") == "cardiac arrhythmia"
    assert is_singular_plural_pair(
        "Cardiac arrhythmia",
        "Cardiac arrhythmias",
    )
    assert is_singular_plural_pair(
        "Cardiac arrhythmia",
        "Cardiac arrhythmia s",
    )
    assert is_singular_plural_pair("Artery", "Arteries")
    assert is_singular_plural_pair("Virus", "Viruses")
    assert not is_singular_plural_pair("Heart disease", "Cardiac disease")
    assert not is_singular_plural_pair("Cardiac arrhythmia", "Arrhythmias")
    assert is_exact_alias_match(
        "Angina pectoris",
        "Angina pectoris - Coronary artery disease",
    )
    assert not is_exact_alias_match(
        "Angina",
        "Angina pectoris - Coronary artery disease",
    )
    assert not is_exact_alias_match("COVID", "COVID-19")


def test_matcher_prefers_exact_without_classifying_plural_candidates() -> None:
    async def scenario() -> None:
        calls = 0

        async def classify(
            candidate: SearchCandidate,
        ) -> PageClassification:
            nonlocal calls
            del candidate
            calls += 1
            return classification(PageType.DISEASE_LIST)

        matcher = SafeCategorySearchMatcher(
            canonicalize_url=lambda url: url,
            allowed_domains=frozenset({"example.test"}),
        )
        result = await matcher.select(
            "Cardiac arrhythmia",
            (
                SearchCandidate(
                    "Cardiac arrhythmias",
                    "https://example.test/arrhythmias",
                ),
                SearchCandidate(
                    "Cardiac arrhythmia",
                    "https://example.test/arrhythmia",
                ),
            ),
            classify=classify,
        )

        assert result.strategy == "exact_normalized"
        assert result.candidate is not None
        assert result.candidate.label == "Cardiac arrhythmia"
        assert calls == 0

    asyncio.run(scenario())


def test_matcher_uses_unique_exact_alias_before_plural_fallback() -> None:
    async def scenario() -> None:
        calls = 0

        async def classify(
            candidate: SearchCandidate,
        ) -> PageClassification:
            nonlocal calls
            del candidate
            calls += 1
            return classification(PageType.DISEASE_DETAIL)

        matcher = SafeCategorySearchMatcher(
            canonicalize_url=lambda url: url,
            allowed_domains=frozenset({"example.test"}),
        )
        matched = await matcher.select(
            "Angina pectoris",
            (
                SearchCandidate(
                    "Angina pectoris - Coronary artery disease",
                    "https://example.test/cad",
                ),
            ),
            classify=classify,
        )

        assert matched.strategy == "alias_exact"
        assert matched.reason_code == "alias_exact_match"
        assert matched.candidate is not None
        assert calls == 0

        ambiguous = await matcher.select(
            "Angina pectoris",
            (
                SearchCandidate(
                    "Angina pectoris - Coronary artery disease",
                    "https://example.test/cad",
                ),
                SearchCandidate(
                    "Angina pectoris - Other disease",
                    "https://example.test/other",
                ),
            ),
            classify=classify,
        )
        assert ambiguous.candidate is None
        assert ambiguous.reason_code == "ambiguous_alias_results"

    asyncio.run(scenario())


def test_plural_match_requires_unique_confirmed_category_and_https_domain() -> None:
    async def scenario() -> None:
        matcher = SafeCategorySearchMatcher(
            canonicalize_url=lambda url: url,
            allowed_domains=frozenset({"example.test"}),
        )

        async def list_classifier(
            candidate: SearchCandidate,
        ) -> PageClassification:
            del candidate
            return classification(PageType.DISEASE_LIST)

        matched = await matcher.select(
            "Cardiac arrhythmia",
            (
                SearchCandidate(
                    "Cardiac arrhythmias",
                    "https://example.test/arrhythmias",
                ),
                SearchCandidate(
                    "Cardiac arrhythmias",
                    "http://example.test/insecure",
                ),
                SearchCandidate(
                    "Cardiac arrhythmias",
                    "https://evil.test/outside",
                ),
            ),
            classify=list_classifier,
        )
        assert matched.reason_code == "singular_plural_category_match"

        async def detail_classifier(
            candidate: SearchCandidate,
        ) -> PageClassification:
            del candidate
            return classification(PageType.DISEASE_DETAIL)

        rejected = await matcher.select(
            "Cardiac arrhythmia",
            (
                SearchCandidate(
                    "Cardiac arrhythmias",
                    "https://example.test/arrhythmias",
                ),
            ),
            classify=detail_classifier,
        )
        assert rejected.candidate is None
        assert rejected.reason_code == "candidate_not_category"

        ambiguous = await matcher.select(
            "Cardiac arrhythmia",
            (
                SearchCandidate(
                    "Cardiac arrhythmias",
                    "https://example.test/one",
                ),
                SearchCandidate(
                    "Cardiac arrhythmias",
                    "https://example.test/two",
                ),
            ),
            classify=list_classifier,
        )
        assert ambiguous.reason_code == "ambiguous_singular_plural_results"

    asyncio.run(scenario())


class DomLocator:
    def __init__(self, elements: list[Tag]) -> None:
        self.elements = elements

    def nth(self, index: int) -> "DomLocator":
        return DomLocator(self.elements[index : index + 1])

    async def count(self) -> int:
        return len(self.elements)

    async def get_attribute(self, name: str) -> str | None:
        value = self.elements[0].get(name)
        return str(value) if value is not None else None

    async def inner_text(self) -> str:
        return self.elements[0].get_text(" ", strip=True)

    def locator(self, selector: str) -> "DomLocator":
        element = self.elements[0]
        if selector == "xpath=ancestor::li[1]":
            parent = element.find_parent("li")
            return DomLocator([parent] if isinstance(parent, Tag) else [])
        return DomLocator(list(element.select(selector)))


class DomPage:
    def __init__(self, html: str, url: str) -> None:
        self.soup = BeautifulSoup(html, "html.parser")
        self.url = url

    def locator(self, selector: str) -> DomLocator:
        return DomLocator(list(self.soup.select(selector)))


class DirectChildPlugin:
    name = "test"
    allowed_domains = frozenset({"example.test"})

    def canonicalize_url(self, url: str) -> str:
        return url

    async def navigate_to_candidate(self, page: Page, candidate: Any) -> None:
        del page, candidate

    async def dismiss_known_popups(self, page: Page) -> int:
        del page
        return 0

    async def classify_page(self, page: Page) -> PageClassification:
        del page
        return classification(PageType.DISEASE_LIST)

    async def wait_for_detail_content(self, page: Page) -> None:
        del page


def test_direct_children_come_only_from_active_immediate_list() -> None:
    async def scenario() -> None:
        page = DomPage(
            """
            <div id="sidemenutree"><ul>
              <li><a href="/sibling">Unrelated sibling</a></li>
              <li><a href="/active">Active category</a>
                <ul>
                  <li><a href="/child-b">Child B</a>
                    <ul><li><a href="/grandchild">Grandchild</a></li></ul>
                  </li>
                  <li><a href="/child-a">Child A</a></li>
                  <li><a href="/edit">Edit</a></li>
                  <li><a href="/plus">+</a></li>
                  <li><a href="https://evil.test/out">Outside</a></li>
                </ul>
              </li>
            </ul></div>
            """,
            "https://example.test/active",
        )
        service = CategoryExpansionService(
            plugin=DirectChildPlugin(),
            policy=CategoryExpansionPolicy(),
        )

        children = await service.direct_children(cast(Page, page))

        assert [child.label for child in children] == ["Child B", "Child A"]
        assert all("grandchild" not in child.url for child in children)
        assert all(child.label not in {"+", "Edit", "Edit note"} for child in children)

    asyncio.run(scenario())
