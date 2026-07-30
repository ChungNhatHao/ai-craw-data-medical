import re
import unicodedata
from collections import deque
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urljoin, urlparse

from playwright.async_api import Page

from app.core.errors import CrawlerError, ErrorCode
from app.core.ids import build_item_id
from app.models.category import (
    CategoryDiscoveryNode,
    CategoryItemProvenance,
    CategoryNodeStatus,
    CategoryReasonCode,
)
from app.models.discovery import DiscoveredItem
from app.models.navigation import NavigationCandidate, PageClassification, PageType

NON_WORD = re.compile(r"[\W_]+", re.UNICODE)
ALIAS_SEPARATOR = re.compile(r"\s+-\s+")
MUTATION_LABELS = frozenset({"+", "edit", "edit note"})
MUTATION_URL_TERMS = frozenset({"edit", "cart", "delete", "logout"})


class CategoryPlugin(Protocol):
    name: str
    allowed_domains: frozenset[str]

    def canonicalize_url(self, url: str) -> str: ...

    async def navigate_to_candidate(
        self,
        page: Page,
        candidate: NavigationCandidate,
    ) -> None: ...

    async def dismiss_known_popups(self, page: Page) -> int: ...

    async def classify_page(self, page: Page) -> PageClassification: ...

    async def wait_for_detail_content(self, page: Page) -> None: ...


@dataclass(frozen=True)
class SearchCandidate:
    label: str
    url: str


@dataclass(frozen=True)
class SearchMatch:
    candidate: SearchCandidate | None
    strategy: str | None
    reason_code: str


@dataclass(frozen=True)
class CategoryExpansionPolicy:
    max_depth: int = 5
    max_nodes: int = 100
    max_diseases: int = 100

    def __post_init__(self) -> None:
        if not 1 <= self.max_depth <= 8:
            raise ValueError("max_depth must be between 1 and 8")
        if not 1 <= self.max_nodes <= 250:
            raise ValueError("max_nodes must be between 1 and 250")
        if not 1 <= self.max_diseases <= 250:
            raise ValueError("max_diseases must be between 1 and 250")


@dataclass(frozen=True)
class CategorySeed:
    root_query: str
    label: str
    url: str


@dataclass(frozen=True)
class CategoryChild:
    label: str
    url: str
    menu_order: int


@dataclass(frozen=True)
class CategoryExpansionResult:
    items: tuple[DiscoveredItem, ...]
    nodes: tuple[CategoryDiscoveryNode, ...]
    provenance: tuple[CategoryItemProvenance, ...]
    visited_count: int
    stopped_reason: str
    limits_reached: tuple[str, ...] = ()


@dataclass(frozen=True)
class _QueuedNode:
    root_query: str
    label: str
    url: str
    parent_url: str | None
    menu_path: tuple[str, ...]
    ancestors: frozenset[str]
    depth: int


Classifier = Callable[[SearchCandidate], Awaitable[PageClassification]]
Progress = Callable[[int, int, int], Awaitable[None]]


class SafeCategorySearchMatcher:
    """Select exact names first and allow only narrow category inflections."""

    def __init__(
        self,
        *,
        canonicalize_url: Callable[[str], str],
        allowed_domains: frozenset[str],
    ) -> None:
        self.canonicalize_url = canonicalize_url
        self.allowed_domains = allowed_domains

    async def select(
        self,
        query: str,
        candidates: Iterable[SearchCandidate],
        *,
        classify: Classifier,
    ) -> SearchMatch:
        safe = self._unique_safe_candidates(candidates)
        normalized_query = normalize_search_name(query)
        exact = [
            candidate
            for candidate in safe
            if normalize_search_name(candidate.label) == normalized_query
        ]
        if exact:
            if len(exact) != 1:
                return SearchMatch(None, None, "ambiguous_exact_results")
            return SearchMatch(exact[0], "exact_normalized", "exact_match")

        aliases = [
            candidate
            for candidate in safe
            if is_exact_alias_match(query, candidate.label)
        ]
        if aliases:
            if len(aliases) != 1:
                return SearchMatch(None, None, "ambiguous_alias_results")
            return SearchMatch(
                aliases[0],
                "alias_exact",
                "alias_exact_match",
            )

        inflections = [
            candidate
            for candidate in safe
            if is_singular_plural_pair(query, candidate.label)
        ]
        if not inflections:
            return SearchMatch(None, None, "exact_title_not_found")
        if len(inflections) != 1:
            return SearchMatch(
                None,
                None,
                "ambiguous_singular_plural_results",
            )
        classification = await classify(inflections[0])
        if classification.page_type is not PageType.DISEASE_LIST:
            return SearchMatch(
                None,
                None,
                "candidate_not_category",
            )
        return SearchMatch(
            inflections[0],
            "singular_plural_category",
            "singular_plural_category_match",
        )

    def _unique_safe_candidates(
        self,
        candidates: Iterable[SearchCandidate],
    ) -> tuple[SearchCandidate, ...]:
        unique: dict[str, SearchCandidate] = {}
        for candidate in candidates:
            canonical = self.canonicalize_url(candidate.url)
            parsed = urlparse(canonical)
            if (
                parsed.scheme != "https"
                or parsed.hostname not in self.allowed_domains
            ):
                continue
            unique.setdefault(
                canonical,
                SearchCandidate(candidate.label, canonical),
            )
        return tuple(unique[url] for url in sorted(unique))


class CategoryExpansionService:
    """Bounded BFS over direct child menu links; only details become items."""

    def __init__(
        self,
        *,
        plugin: CategoryPlugin,
        policy: CategoryExpansionPolicy,
    ) -> None:
        self.plugin = plugin
        self.policy = policy

    async def run(
        self,
        page: Page,
        *,
        job_id: str,
        seeds: Iterable[CategorySeed],
        progress: Progress | None = None,
    ) -> CategoryExpansionResult:
        queue = deque(
            _QueuedNode(
                root_query=seed.root_query,
                label=seed.label,
                url=seed.url,
                parent_url=None,
                menu_path=(seed.label,),
                ancestors=frozenset(),
                depth=0,
            )
            for seed in seeds
        )
        visited: set[str] = set()
        classifications: dict[str, PageClassification] = {}
        cached_children: dict[str, tuple[CategoryChild, ...]] = {}
        items: dict[str, DiscoveredItem] = {}
        nodes: list[CategoryDiscoveryNode] = []
        provenance: list[CategoryItemProvenance] = []
        provenance_keys: set[tuple[str, str, tuple[str, ...]]] = set()
        limits: list[str] = []
        stopped_reason = "category_queue_exhausted"

        while queue:
            if len(visited) >= self.policy.max_nodes:
                limits.append("category_node_limit")
                stopped_reason = "category_node_limit"
                for remaining in queue:
                    nodes.append(
                        self._audit(
                            remaining,
                            PageType.UNKNOWN,
                            0,
                            CategoryNodeStatus.LIMIT_REACHED,
                            CategoryReasonCode.CATEGORY_NODE_LIMIT,
                        )
                    )
                break
            if len(items) >= self.policy.max_diseases:
                limits.append("category_disease_limit")
                stopped_reason = "category_disease_limit"
                for remaining in queue:
                    nodes.append(
                        self._audit(
                            remaining,
                            PageType.UNKNOWN,
                            0,
                            CategoryNodeStatus.LIMIT_REACHED,
                            CategoryReasonCode.CATEGORY_DISEASE_LIMIT,
                        )
                    )
                break

            node = queue.popleft()
            canonical = self.plugin.canonicalize_url(node.url)
            if not self._is_allowed(canonical):
                nodes.append(
                    self._audit(
                        node,
                        PageType.UNKNOWN,
                        0,
                        CategoryNodeStatus.SKIPPED,
                        CategoryReasonCode.CANDIDATE_NOT_DISEASE_DETAIL,
                    )
                )
                continue
            if canonical in node.ancestors:
                nodes.append(
                    self._audit(
                        node,
                        PageType.UNKNOWN,
                        0,
                        CategoryNodeStatus.SKIPPED,
                        CategoryReasonCode.DUPLICATE_CANONICAL_URL,
                    )
                )
                continue
            if canonical in visited:
                await self._replay_cached_node(
                    node,
                    canonical,
                    classifications,
                    cached_children,
                    items,
                    nodes,
                    provenance,
                    provenance_keys,
                    queue,
                    job_id,
                )
                continue

            visited.add(canonical)
            try:
                await self.plugin.navigate_to_candidate(
                    page,
                    NavigationCandidate(
                        key=canonical,
                        action="goto",
                        target=canonical,
                        label=node.label,
                        url=canonical,
                    ),
                )
                await self.plugin.dismiss_known_popups(page)
                classification = await self.plugin.classify_page(page)
            except CrawlerError as exc:
                if exc.code in {
                    ErrorCode.AUTH_SESSION_EXPIRED,
                    ErrorCode.AUTH_MFA_OR_CAPTCHA,
                }:
                    raise
                nodes.append(
                    self._audit(
                        node,
                        PageType.UNKNOWN,
                        0,
                        CategoryNodeStatus.SKIPPED,
                        CategoryReasonCode.PAGE_TYPE_UNKNOWN,
                    )
                )
                continue

            classifications[canonical] = classification
            self._raise_for_terminal_page(classification)
            if classification.page_type is PageType.DISEASE_DETAIL:
                await self._confirm_detail(
                    page,
                    node,
                    canonical,
                    classification,
                    items,
                    nodes,
                    provenance,
                    provenance_keys,
                    job_id,
                )
            elif classification.page_type is PageType.DISEASE_LIST:
                if node.depth >= self.policy.max_depth:
                    limits.append("category_depth_limit")
                    nodes.append(
                        self._audit(
                            node,
                            PageType.DISEASE_LIST,
                            classification.confidence,
                            CategoryNodeStatus.LIMIT_REACHED,
                            CategoryReasonCode.CATEGORY_DEPTH_LIMIT,
                        )
                    )
                    continue
                children = await self.direct_children(page)
                cached_children[canonical] = children
                nodes.append(
                    self._audit(
                        node,
                        PageType.DISEASE_LIST,
                        classification.confidence,
                        CategoryNodeStatus.CONFIRMED,
                        CategoryReasonCode.CATEGORY_CONFIRMED
                        if children
                        else CategoryReasonCode.CATEGORY_EMPTY,
                    )
                )
                self._enqueue_children(
                    queue,
                    nodes,
                    node,
                    canonical,
                    children,
                )
            else:
                nodes.append(
                    self._audit(
                        node,
                        classification.page_type,
                        classification.confidence,
                        CategoryNodeStatus.SKIPPED,
                        CategoryReasonCode.PAGE_TYPE_UNKNOWN
                        if classification.page_type is PageType.UNKNOWN
                        else CategoryReasonCode.CANDIDATE_NOT_DISEASE_DETAIL,
                    )
                )
            if progress is not None:
                await progress(len(visited), len(queue), len(items))

        return CategoryExpansionResult(
            items=tuple(items[key] for key in sorted(items)),
            nodes=tuple(nodes),
            provenance=tuple(provenance),
            visited_count=len(visited),
            stopped_reason=stopped_reason,
            limits_reached=tuple(dict.fromkeys(limits)),
        )

    async def direct_children(self, page: Page) -> tuple[CategoryChild, ...]:
        current_url = self.plugin.canonicalize_url(page.url)
        links = page.locator("#sidemenutree a[href]")
        active = None
        for index in range(await links.count()):
            link = links.nth(index)
            href = await link.get_attribute("href")
            if href and self.plugin.canonicalize_url(
                urljoin(page.url, href)
            ) == current_url:
                active = link
                break
        if active is None or not hasattr(active, "locator"):
            return ()
        branch = active.locator("xpath=ancestor::li[1]")
        if not await branch.count():
            return ()
        links = branch.locator(":scope > ul > li > a[href]")
        children: list[CategoryChild] = []
        seen: set[str] = set()
        for index in range(await links.count()):
            link = links.nth(index)
            href = (await link.get_attribute("href") or "").strip()
            label = " ".join((await link.inner_text()).split())
            canonical = self.plugin.canonicalize_url(urljoin(page.url, href))
            if (
                not href
                or not label
                or self._is_mutation(label, canonical)
                or not self._is_allowed(canonical)
                or canonical == current_url
                or canonical in seen
            ):
                continue
            seen.add(canonical)
            children.append(CategoryChild(label, canonical, index))
        return tuple(
            sorted(children, key=lambda child: (child.menu_order, child.url))
        )

    async def _confirm_detail(
        self,
        page: Page,
        node: _QueuedNode,
        canonical: str,
        first: PageClassification,
        items: dict[str, DiscoveredItem],
        nodes: list[CategoryDiscoveryNode],
        provenance: list[CategoryItemProvenance],
        provenance_keys: set[tuple[str, str, tuple[str, ...]]],
        job_id: str,
    ) -> None:
        try:
            await self.plugin.wait_for_detail_content(page)
            second = await self.plugin.classify_page(page)
        except CrawlerError as exc:
            if exc.code in {
                ErrorCode.AUTH_SESSION_EXPIRED,
                ErrorCode.AUTH_MFA_OR_CAPTCHA,
            }:
                raise
            nodes.append(
                self._audit(
                    node,
                    PageType.DISEASE_DETAIL,
                    first.confidence,
                    CategoryNodeStatus.SKIPPED,
                    CategoryReasonCode.CONTENT_NOT_READY,
                )
            )
            return
        except NotImplementedError:
            nodes.append(
                self._audit(
                    node,
                    PageType.DISEASE_DETAIL,
                    first.confidence,
                    CategoryNodeStatus.SKIPPED,
                    CategoryReasonCode.CONTENT_NOT_READY,
                )
            )
            return
        self._raise_for_terminal_page(second)
        if second.page_type is not PageType.DISEASE_DETAIL:
            nodes.append(
                self._audit(
                    node,
                    second.page_type,
                    second.confidence,
                    CategoryNodeStatus.SKIPPED,
                    CategoryReasonCode.CANDIDATE_NOT_STABLE_DISEASE_DETAIL,
                )
            )
            return
        item_id = build_item_id(self.plugin.name, canonical)
        items.setdefault(
            item_id,
            DiscoveredItem(
                item_id=item_id,
                source_url=canonical,
                canonical_url=canonical,
                title_hint=node.label,
                discovery_page=node.parent_url or canonical,
            ),
        )
        nodes.append(
            self._audit(
                node,
                PageType.DISEASE_DETAIL,
                min(first.confidence, second.confidence),
                CategoryNodeStatus.CONFIRMED,
                CategoryReasonCode.DISEASE_DETAIL_CONFIRMED,
            )
        )
        self._add_provenance(
            item_id,
            node,
            provenance,
            provenance_keys,
            job_id,
        )

    async def _replay_cached_node(
        self,
        node: _QueuedNode,
        canonical: str,
        classifications: dict[str, PageClassification],
        cached_children: dict[str, tuple[CategoryChild, ...]],
        items: dict[str, DiscoveredItem],
        nodes: list[CategoryDiscoveryNode],
        provenance: list[CategoryItemProvenance],
        provenance_keys: set[tuple[str, str, tuple[str, ...]]],
        queue: deque[_QueuedNode],
        job_id: str,
    ) -> None:
        classification = classifications.get(canonical)
        nodes.append(
            self._audit(
                node,
                classification.page_type
                if classification is not None
                else PageType.UNKNOWN,
                classification.confidence if classification is not None else 0,
                CategoryNodeStatus.SKIPPED,
                CategoryReasonCode.DUPLICATE_CANONICAL_URL,
            )
        )
        if classification is None:
            return
        if classification.page_type is PageType.DISEASE_DETAIL:
            item_id = build_item_id(self.plugin.name, canonical)
            if item_id in items:
                self._add_provenance(
                    item_id,
                    node,
                    provenance,
                    provenance_keys,
                    job_id,
                )
        elif (
            classification.page_type is PageType.DISEASE_LIST
            and node.depth < self.policy.max_depth
        ):
            self._enqueue_children(
                queue,
                nodes,
                node,
                canonical,
                cached_children.get(canonical, ()),
            )

    def _enqueue_children(
        self,
        queue: deque[_QueuedNode],
        nodes: list[CategoryDiscoveryNode],
        parent: _QueuedNode,
        canonical_parent: str,
        children: tuple[CategoryChild, ...],
    ) -> None:
        ancestors = parent.ancestors | {canonical_parent}
        for child in children:
            queued = _QueuedNode(
                root_query=parent.root_query,
                label=child.label,
                url=child.url,
                parent_url=canonical_parent,
                menu_path=(*parent.menu_path, child.label),
                ancestors=ancestors,
                depth=parent.depth + 1,
            )
            queue.append(queued)
            nodes.append(
                self._audit(
                    queued,
                    PageType.UNKNOWN,
                    0,
                    CategoryNodeStatus.QUEUED,
                    CategoryReasonCode.CATEGORY_CHILD_ENQUEUED,
                )
            )

    def _add_provenance(
        self,
        item_id: str,
        node: _QueuedNode,
        provenance: list[CategoryItemProvenance],
        keys: set[tuple[str, str, tuple[str, ...]]],
        job_id: str,
    ) -> None:
        key = (item_id, node.root_query, node.menu_path)
        if key in keys:
            return
        keys.add(key)
        provenance.append(
            CategoryItemProvenance(
                job_id=job_id,
                item_id=item_id,
                root_query=node.root_query,
                parent_url=node.parent_url,
                menu_path=node.menu_path,
                depth=node.depth,
            )
        )

    def _audit(
        self,
        node: _QueuedNode,
        page_type: PageType,
        confidence: float,
        status: CategoryNodeStatus,
        reason_code: CategoryReasonCode,
    ) -> CategoryDiscoveryNode:
        return CategoryDiscoveryNode(
            root_query=node.root_query,
            label=node.label,
            url=node.url,
            canonical_url=self.plugin.canonicalize_url(node.url),
            parent_url=node.parent_url,
            menu_path=node.menu_path,
            depth=node.depth,
            page_type=page_type,
            confidence=confidence,
            status=status,
            reason_code=reason_code,
        )

    def _is_allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        return (
            parsed.scheme == "https"
            and parsed.hostname in self.plugin.allowed_domains
        )

    def _is_mutation(self, label: str, url: str) -> bool:
        normalized_label = normalize_search_name(label)
        raw_label = " ".join(label.casefold().split())
        path = urlparse(url).path.casefold()
        return (
            raw_label in MUTATION_LABELS
            or normalized_label in MUTATION_LABELS
            or any(term in path for term in MUTATION_URL_TERMS)
        )

    def _raise_for_terminal_page(
        self,
        classification: PageClassification,
    ) -> None:
        if classification.page_type is PageType.LOGIN:
            raise CrawlerError(
                ErrorCode.AUTH_SESSION_EXPIRED,
                "Category traversal reached the login page",
            )
        if classification.page_type is PageType.BLOCKED_OR_CAPTCHA:
            raise CrawlerError(
                ErrorCode.AUTH_MFA_OR_CAPTCHA,
                "Category traversal requires operator action",
            )


def normalize_search_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    tokens = NON_WORD.sub(" ", normalized).split()
    # Search results wrap the matched part in markup. BeautifulSoup can expose
    # a highlighted plural suffix as "arrhythmia s"; join only that narrow
    # final suffix so safe singular/plural comparison still works.
    if len(tokens) >= 2 and tokens[-1] in {"s", "es"}:
        tokens[-2] = f"{tokens[-2]}{tokens[-1]}"
        tokens.pop()
    return " ".join(tokens)


def autocomplete_label_parts(value: str) -> tuple[str, ...]:
    return tuple(
        part
        for raw in ALIAS_SEPARATOR.split(value)
        if (part := " ".join(raw.split()))
    )


def is_exact_alias_match(query: str, label: str) -> bool:
    parts = autocomplete_label_parts(label)
    if len(parts) < 2:
        return False
    normalized_query = normalize_search_name(query)
    return any(
        normalize_search_name(alias) == normalized_query
        for alias in parts[:-1]
    )


def is_singular_plural_pair(left: str, right: str) -> bool:
    left_tokens = normalize_search_name(left).split()
    right_tokens = normalize_search_name(right).split()
    if (
        not left_tokens
        or len(left_tokens) != len(right_tokens)
        or left_tokens[:-1] != right_tokens[:-1]
        or left_tokens[-1] == right_tokens[-1]
    ):
        return False
    return (
        right_tokens[-1] in _plural_forms(left_tokens[-1])
        or left_tokens[-1] in _plural_forms(right_tokens[-1])
    )


def _plural_forms(token: str) -> frozenset[str]:
    if len(token) > 1 and token.endswith("y") and token[-2] not in "aeiou":
        return frozenset({f"{token[:-1]}ies"})
    if token.endswith(("s", "x", "z", "ch", "sh")):
        return frozenset({f"{token}es"})
    return frozenset({f"{token}s"})
