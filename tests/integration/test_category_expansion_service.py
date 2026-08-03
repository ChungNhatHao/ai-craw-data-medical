import asyncio
from typing import Any, cast

from playwright.async_api import Page

from app.models.navigation import PageClassification, PageType
from app.services.category_expansion import (
    CategoryChild,
    CategoryExpansionPolicy,
    CategoryExpansionService,
    CategorySeed,
)

BASE = "https://example.test"
ROOT_A = f"{BASE}/root-a"
ROOT_B = f"{BASE}/root-b"
SUBCATEGORY = f"{BASE}/subcategory"
SHARED = f"{BASE}/shared-disease"
DETAIL = f"{BASE}/detail"


def classified(page_type: PageType, url: str) -> PageClassification:
    return PageClassification(
        page_type=page_type,
        confidence=1,
        fingerprint=(f"{page_type.value}:{url}").ljust(12, "x"),
    )


class FakePage:
    url = ROOT_A


class FakeCategoryPlugin:
    name = "fake-category"
    allowed_domains = frozenset({"example.test"})

    def __init__(self) -> None:
        self.page_types = {
            ROOT_A: PageType.DISEASE_LIST,
            ROOT_B: PageType.DISEASE_LIST,
            SUBCATEGORY: PageType.DISEASE_LIST,
            SHARED: PageType.DISEASE_DETAIL,
            DETAIL: PageType.DISEASE_DETAIL,
        }
        self.navigation_count: dict[str, int] = {}

    def canonicalize_url(self, url: str) -> str:
        return url.rstrip("/")

    async def navigate_to_candidate(self, page: Page, candidate: Any) -> None:
        page.url = candidate.target
        self.navigation_count[page.url] = self.navigation_count.get(page.url, 0) + 1

    async def dismiss_known_popups(self, page: Page) -> int:
        del page
        return 0

    async def classify_page(self, page: Page) -> PageClassification:
        return classified(self.page_types.get(page.url, PageType.UNKNOWN), page.url)

    async def wait_for_detail_content(self, page: Page) -> None:
        del page


class FakeExpansionService(CategoryExpansionService):
    async def direct_children(self, page: Page) -> tuple[CategoryChild, ...]:
        children = {
            ROOT_A: (
                CategoryChild("Nested category", SUBCATEGORY, 0),
                CategoryChild("Shared disease", SHARED, 1),
            ),
            ROOT_B: (CategoryChild("Shared disease", SHARED, 0),),
            SUBCATEGORY: (
                CategoryChild("Final disease", DETAIL, 0),
                CategoryChild("Cycle", ROOT_A, 1),
            ),
        }
        return children.get(page.url, ())


def test_bounded_bfs_confirms_only_details_and_preserves_multiple_paths() -> None:
    async def scenario() -> None:
        plugin = FakeCategoryPlugin()
        service = FakeExpansionService(
            plugin=plugin,
            policy=CategoryExpansionPolicy(
                max_depth=5,
                max_nodes=20,
                max_diseases=10,
            ),
        )

        result = await service.run(
            cast(Page, FakePage()),
            job_id="job-category",
            seeds=(
                CategorySeed("Root A query", "Root A", ROOT_A),
                CategorySeed("Root B query", "Root B", ROOT_B),
            ),
        )

        assert len(result.items) == 2
        assert {str(item.canonical_url).rstrip("/") for item in result.items} == {
            SHARED,
            DETAIL,
        }
        assert plugin.navigation_count[SHARED] == 1
        assert all(
            str(item.canonical_url).rstrip("/") not in {ROOT_A, ROOT_B, SUBCATEGORY}
            for item in result.items
        )
        shared_item = next(
            item
            for item in result.items
            if str(item.canonical_url).rstrip("/") == SHARED
        )
        shared_paths = [
            row
            for row in result.provenance
            if row.item_id == shared_item.item_id
        ]
        assert {row.root_query for row in shared_paths} == {
            "Root A query",
            "Root B query",
        }
        assert any(
            node.reason_code == "duplicate_canonical_url"
            for node in result.nodes
        )
        assert any(
            node.reason_code == "disease_detail_confirmed"
            for node in result.nodes
        )
        assert result.stopped_reason == "category_queue_exhausted"

    asyncio.run(scenario())


def test_depth_limit_is_partial_and_does_not_promote_category() -> None:
    async def scenario() -> None:
        plugin = FakeCategoryPlugin()
        result = await FakeExpansionService(
            plugin=plugin,
            policy=CategoryExpansionPolicy(
                max_depth=1,
                max_nodes=20,
                max_diseases=10,
            ),
        ).run(
            cast(Page, FakePage()),
            job_id="job-category",
            seeds=(CategorySeed("Root A query", "Root A", ROOT_A),),
        )

        assert {str(item.canonical_url).rstrip("/") for item in result.items} == {
            SHARED
        }
        assert "category_depth_limit" in result.limits_reached
        depth_node = next(
            node
            for node in result.nodes
            if node.reason_code == "category_depth_limit"
        )
        assert str(depth_node.canonical_url).rstrip("/") == SUBCATEGORY
        assert depth_node.status == "limit_reached"

    asyncio.run(scenario())


def test_node_limit_stops_gracefully_with_reason_codes() -> None:
    async def scenario() -> None:
        result = await FakeExpansionService(
            plugin=FakeCategoryPlugin(),
            policy=CategoryExpansionPolicy(
                max_depth=5,
                max_nodes=1,
                max_diseases=10,
            ),
        ).run(
            cast(Page, FakePage()),
            job_id="job-category",
            seeds=(CategorySeed("Root A query", "Root A", ROOT_A),),
        )

        assert result.items == ()
        assert result.stopped_reason == "category_node_limit"
        assert result.limits_reached == ("category_node_limit",)
        assert any(
            node.reason_code == "category_node_limit"
            for node in result.nodes
        )

    asyncio.run(scenario())


def test_duplicate_seed_is_not_enqueued_or_expanded_twice() -> None:
    async def scenario() -> None:
        plugin = FakeCategoryPlugin()
        result = await FakeExpansionService(
            plugin=plugin,
            policy=CategoryExpansionPolicy(
                max_depth=5,
                max_nodes=20,
                max_diseases=10,
            ),
        ).run(
            cast(Page, FakePage()),
            job_id="job-category",
            seeds=(
                CategorySeed("Root A query", "Root A", ROOT_A),
                CategorySeed("Root A query", "Root A duplicate", ROOT_A),
            ),
        )

        assert plugin.navigation_count[ROOT_A] == 1
        assert result.visited_count == 4
        assert result.stopped_reason == "category_queue_exhausted"
        assert sum(
            node.reason_code == "category_child_enqueued"
            for node in result.nodes
        ) == 3
        assert any(
            node.reason_code == "duplicate_canonical_url"
            for node in result.nodes
        )

    asyncio.run(scenario())
