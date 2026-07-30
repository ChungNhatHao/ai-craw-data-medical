import re
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.agents.autocomplete_selection_agent import AutocompleteSelectionAgent
from app.core.errors import CrawlerError, ErrorCode
from app.core.ids import build_item_id
from app.models.agentic import AutocompleteSuggestion
from app.models.category import (
    CATEGORY_REASON_ACTIONS_VI,
    CATEGORY_REASON_VI,
    CategoryReasonCode,
)
from app.models.discovery import DiscoveredItem
from app.models.imports import ImportSearchAttempt, ImportSearchAudit
from app.models.navigation import (
    NavigationCandidate,
    PageClassification,
    PageType,
)
from app.plugins.genre_manuals.plugin import GenreManualsPlugin
from app.repositories.category_provenance import CategoryProvenanceRepository
from app.repositories.items import ItemRepository
from app.services.category_expansion import (
    CategoryExpansionPolicy,
    CategoryExpansionResult,
    CategoryExpansionService,
    CategorySeed,
    SafeCategorySearchMatcher,
    SearchCandidate,
    SearchMatch,
    autocomplete_label_parts,
    is_exact_alias_match,
    normalize_search_name,
)
from app.storage.artifacts import ArtifactStore

ImportProgress = Callable[
    [int, int, int, str, str],
    Awaitable[None],
]


@dataclass(frozen=True)
class SearchOutcome:
    url: str
    reason_code: str | None
    reason: str | None
    steps: tuple[str, ...]
    submitted_query: str | None = None
    suggestions: tuple[AutocompleteSuggestion, ...] = ()
    selected_suggestions: tuple[str, ...] = ()
    resolved_suggestions: tuple[str, ...] = ()
    decision_source: str = "none"
    decision_confidence: float | None = None
    decision_reason_code: str | None = None
    decision_reason: str | None = None
    result_html: str = ""


@dataclass(frozen=True)
class CandidateScan:
    candidate: DiscoveredItem | None
    inspected_links: int
    exact_matches: int
    strategy: str | None = None


@dataclass(frozen=True)
class ConfirmationOutcome:
    matched: bool
    reason_code: str
    reason: str
    steps: tuple[str, ...]


@dataclass(frozen=True)
class RootSearchRecord:
    disease_name: str
    search: SearchOutcome
    inspected_links: int
    exact_matches: int
    matches: tuple[SearchMatch, ...]


class ImportedDiseaseDiscoveryService:
    """Find explicitly imported disease names through the site's search form."""

    def __init__(
        self,
        *,
        plugin: GenreManualsPlugin,
        items: ItemRepository,
        artifacts: ArtifactStore,
        autocomplete_agent: AutocompleteSelectionAgent | None = None,
    ) -> None:
        self.plugin = plugin
        self.items = items
        self.artifacts = artifacts
        self.autocomplete_agent = autocomplete_agent

    async def run(
        self,
        page: Page,
        *,
        job_id: str,
        disease_names: tuple[str, ...],
        progress: ImportProgress,
    ) -> tuple[list[DiscoveredItem], tuple[str, ...]]:
        discovered: dict[str, DiscoveredItem] = {}
        unmatched: list[str] = []
        attempts: list[ImportSearchAttempt] = []
        total = len(disease_names)
        for processed, disease_name in enumerate(disease_names, start=1):
            variants = await self._search_variants(page, disease_name)
            search = variants[0]
            inspected_links = 0
            exact_matches = 0
            match_strategies: set[str] = set()
            accepted: list[DiscoveredItem] = []
            detail_steps: list[str] = []
            for variant in variants:
                detail_steps.extend(variant.steps)
                if variant.reason_code is not None:
                    continue
                scan = self.analyze_exact_candidates(
                    variant.result_html,
                    query=variant.submitted_query or disease_name,
                    result_page=variant.url,
                )
                inspected_links += scan.inspected_links
                exact_matches += scan.exact_matches
                if scan.strategy is not None:
                    match_strategies.add(scan.strategy)
                if scan.candidate is None:
                    continue
                confirmation = await self._confirm_detail(
                    page,
                    scan.candidate,
                )
                detail_steps.extend(confirmation.steps)
                if confirmation.matched:
                    accepted.append(scan.candidate)
            accepted_by_id = {value.item_id: value for value in accepted}
            accepted = list(accepted_by_id.values())
            selected_urls = tuple(
                str(value.canonical_url) for value in accepted
            )
            matched = bool(accepted)
            reason_code = (
                "autocomplete_candidates_confirmed"
                if matched
                else (
                    search.reason_code
                    or "autocomplete_candidates_not_confirmed"
                )
            )
            reason = (
                f"Đã xác nhận {len(accepted)} trang bệnh từ "
                f"{len(variants)} tên tìm kiếm"
                if matched
                else "Không có gợi ý tìm kiếm nào được xác nhận là trang bệnh"
            )
            steps = (
                *detail_steps,
                (
                    f"Đối chiếu {inspected_links} link; "
                    f"{exact_matches} kết quả khớp tên hợp lệ"
                ),
            )
            attempts.append(
                ImportSearchAttempt(
                    disease_name=disease_name,
                    query=disease_name,
                    search_url=search.url,
                    inspected_links=inspected_links,
                    exact_matches=exact_matches,
                    autocomplete_suggestions=tuple(
                        value.label for value in search.suggestions
                    ),
                    autocomplete_selected_name=(
                        search.selected_suggestions[0]
                        if search.selected_suggestions
                        else None
                    ),
                    autocomplete_selected_names=search.selected_suggestions,
                    autocomplete_resolved_names=search.resolved_suggestions,
                    autocomplete_decision_source=search.decision_source,
                    autocomplete_confidence=search.decision_confidence,
                    autocomplete_reason_code=search.decision_reason_code,
                    autocomplete_reason=search.decision_reason,
                    match_strategy=(
                        "alias_exact"
                        if "alias_exact" in match_strategies
                        else (
                            "exact_normalized"
                            if "exact_normalized" in match_strategies
                            else None
                        )
                    ),
                    selected_url=selected_urls[0] if selected_urls else None,
                    selected_urls=selected_urls,
                    confirmed_disease_count=len(accepted),
                    status="matched" if matched else "not_found",
                    reason_code=reason_code,
                    reason=reason,
                    steps=steps,
                )
            )
            if not matched:
                unmatched.append(disease_name)
                await progress(
                    len(discovered),
                    processed,
                    total,
                    disease_name,
                    "not_found",
                )
                continue
            for candidate in accepted:
                discovered.setdefault(candidate.item_id, candidate)
            await progress(
                len(discovered),
                processed,
                total,
                disease_name,
                "matched",
            )

        selected = list(discovered.values())
        await self.items.upsert_discovered(job_id, selected)
        audit = ImportSearchAudit(
            job_id=job_id,
            requested_count=total,
            matched_count=len(selected),
            not_found_count=len(unmatched),
            attempts=tuple(attempts),
        )
        self.artifacts.persist_import_search_audit(
            job_id,
            audit.model_dump(mode="json"),
        )
        return selected, tuple(unmatched)

    async def run_with_category_expansion(
        self,
        page: Page,
        *,
        job_id: str,
        disease_names: tuple[str, ...],
        policy: CategoryExpansionPolicy,
        provenance_repository: CategoryProvenanceRepository,
        progress: ImportProgress,
        category_progress: Callable[
            [int, int, int],
            Awaitable[None],
        ]
        | None = None,
    ) -> tuple[list[DiscoveredItem], tuple[str, ...]]:
        matcher = SafeCategorySearchMatcher(
            canonicalize_url=self.plugin.canonicalize_url,
            allowed_domains=self.plugin.allowed_domains,
        )
        records: list[RootSearchRecord] = []
        seeds: list[CategorySeed] = []
        total = len(disease_names)

        for processed, disease_name in enumerate(disease_names, start=1):
            variants = await self._search_variants(page, disease_name)
            search = variants[0]
            if search.reason_code is not None:
                match = SearchMatch(
                    None,
                    None,
                    search.reason_code,
                )
                records.append(
                    RootSearchRecord(
                        disease_name,
                        search,
                        0,
                        0,
                        (match,),
                    )
                )
                await progress(
                    len(seeds),
                    processed,
                    total,
                    disease_name,
                    "not_found",
                )
                continue

            async def classify(
                candidate: SearchCandidate,
            ) -> PageClassification:
                await self.plugin.navigate_to_candidate(
                    page,
                    NavigationCandidate(
                        key=candidate.url,
                        action="goto",
                        target=candidate.url,
                        label=candidate.label,
                        url=candidate.url,
                    ),
                )
                await self.plugin.dismiss_known_popups(page)
                classification = await self.plugin.classify_page(page)
                if classification.page_type is PageType.LOGIN:
                    raise CrawlerError(
                        ErrorCode.AUTH_SESSION_EXPIRED,
                        "Search candidate returned to login",
                    )
                if classification.page_type is PageType.BLOCKED_OR_CAPTCHA:
                    raise CrawlerError(
                        ErrorCode.AUTH_MFA_OR_CAPTCHA,
                        "Search candidate encountered CAPTCHA or block",
                    )
                return classification

            matches: list[SearchMatch] = []
            inspected_links = 0
            exact_matches = 0
            for variant in variants:
                if variant.reason_code is not None:
                    continue
                candidates, inspected = self._search_candidates(
                    variant.result_html,
                    result_page=variant.url,
                )
                inspected_links += inspected
                query = variant.submitted_query or disease_name
                exact_matches += sum(
                    1
                    for candidate in candidates
                    if normalize_search_name(candidate.label)
                    == normalize_search_name(query)
                )
                matches.append(
                    await matcher.select(
                        query,
                        candidates,
                        classify=classify,
                    )
                )
            records.append(
                RootSearchRecord(
                    disease_name,
                    search,
                    inspected_links,
                    exact_matches,
                    tuple(matches),
                )
            )
            for match in matches:
                if match.candidate is not None:
                    seeds.append(
                        CategorySeed(
                            root_query=disease_name,
                            label=match.candidate.label,
                            url=match.candidate.url,
                        )
                    )
            await progress(
                len(seeds),
                processed,
                total,
                disease_name,
                (
                    "matched"
                    if any(value.candidate is not None for value in matches)
                    else "not_found"
                ),
            )

        expansion = await CategoryExpansionService(
            plugin=self.plugin,
            policy=policy,
        ).run(
            page,
            job_id=job_id,
            seeds=seeds,
            progress=category_progress,
        )
        selected = list(expansion.items)
        await self.items.upsert_discovered(job_id, selected)
        await provenance_repository.upsert_many(list(expansion.provenance))
        self._persist_category_expansion(job_id, expansion)

        confirmed_by_root = Counter(
            value.root_query for value in expansion.provenance
        )
        root_categories = {
            value.root_query
            for value in expansion.nodes
            if value.depth == 0 and value.page_type is PageType.DISEASE_LIST
        }
        attempts: list[ImportSearchAttempt] = []
        unmatched: list[str] = []
        for record in records:
            confirmed_count = confirmed_by_root[record.disease_name]
            matched_candidates = tuple(
                value.candidate
                for value in record.matches
                if value.candidate is not None
            )
            selected_urls = tuple(
                value.url for value in matched_candidates
            )
            if not matched_candidates:
                unmatched.append(record.disease_name)
                reason_code = (
                    record.matches[0].reason_code
                    if record.matches
                    else "exact_title_not_found"
                )
                reason = self._category_reason(reason_code)
                status = "not_found"
            elif confirmed_count == 0:
                unmatched.append(record.disease_name)
                reason_code = "category_no_confirmed_disease"
                reason = (
                    "Đã chọn kết quả tìm kiếm nhưng không xác nhận được "
                    "trang bệnh con nào"
                )
                status = "not_found"
            else:
                reason_code = (
                    "category_confirmed"
                    if record.disease_name in root_categories
                    else "disease_detail_confirmed"
                )
                reason = self._category_reason(reason_code)
                status = "matched"
            attempts.append(
                ImportSearchAttempt(
                    disease_name=record.disease_name,
                    query=record.disease_name,
                    search_url=record.search.url,
                    inspected_links=record.inspected_links,
                    exact_matches=record.exact_matches,
                    autocomplete_suggestions=tuple(
                        value.label for value in record.search.suggestions
                    ),
                    autocomplete_selected_name=(
                        record.search.selected_suggestions[0]
                        if record.search.selected_suggestions
                        else None
                    ),
                    autocomplete_selected_names=(
                        record.search.selected_suggestions
                    ),
                    autocomplete_resolved_names=(
                        record.search.resolved_suggestions
                    ),
                    autocomplete_decision_source=(
                        record.search.decision_source
                    ),
                    autocomplete_confidence=(
                        record.search.decision_confidence
                    ),
                    autocomplete_reason_code=(
                        record.search.decision_reason_code
                    ),
                    autocomplete_reason=record.search.decision_reason,
                    match_strategy=(
                        "autocomplete_multi_candidate"
                        if len(matched_candidates) > 1
                        else (
                            record.matches[0].strategy
                            if record.matches
                            else None
                        )
                    ),
                    search_reason_code=(
                        record.search.decision_reason_code
                        if len(matched_candidates) > 1
                        else (
                            record.matches[0].reason_code
                            if record.matches
                            else "exact_title_not_found"
                        )
                    ),
                    selected_url=selected_urls[0] if selected_urls else None,
                    selected_urls=selected_urls,
                    confirmed_disease_count=confirmed_count,
                    status=status,
                    reason_code=reason_code,
                    reason=reason,
                    steps=(
                        *record.search.steps,
                        (
                            f"Đã xác minh {len(matched_candidates)}/"
                            f"{len(record.matches)} gợi ý autocomplete"
                        ),
                        (
                            f"Mở rộng cây xác nhận {confirmed_count} "
                            "trang bệnh cho tên gốc"
                        ),
                    ),
                )
            )

        audit = ImportSearchAudit(
            job_id=job_id,
            requested_count=total,
            matched_count=total - len(unmatched),
            not_found_count=len(unmatched),
            category_expansion_enabled=True,
            confirmed_disease_count=len(selected),
            attempts=tuple(attempts),
        )
        self.artifacts.persist_import_search_audit(
            job_id,
            audit.model_dump(mode="json"),
        )
        return selected, tuple(unmatched)

    async def _search(self, page: Page, disease_name: str) -> SearchOutcome:
        steps: list[str] = []
        search = page.locator("#searchTerm")
        if not await search.count():
            try:
                await page.goto(
                    self.plugin.base_url,
                    wait_until="domcontentloaded",
                    timeout=self.plugin.navigation_timeout_ms,
                )
                steps.append("Đã quay lại trang gốc để tìm ô #searchTerm")
            except PlaywrightError:
                return SearchOutcome(
                    page.url,
                    "search_home_navigation_failed",
                    "Không thể quay lại trang gốc để mở form tìm kiếm",
                    tuple(steps),
                )
            search = page.locator("#searchTerm")
        if not await search.count():
            return SearchOutcome(
                page.url,
                "search_input_not_found",
                "Không tìm thấy ô Start searching… (#searchTerm)",
                tuple(steps),
            )
        await search.fill("")
        await search.press_sequentially(disease_name, delay=35)
        steps.append(f"Đã nhập truy vấn vào #searchTerm: {disease_name}")
        suggestions = await self._collect_autocomplete_suggestions(page)
        submitted_query = disease_name
        selected_suggestions: tuple[str, ...] = ()
        resolved_suggestions: tuple[str, ...] = ()
        decision_source = "none"
        decision_confidence: float | None = None
        decision_reason_code: str | None = None
        decision_reason: str | None = None
        if suggestions:
            steps.append(
                f"Đã thu thập {len(suggestions)} gợi ý autocomplete"
            )
            if self.autocomplete_agent is None:
                decision_source = "deterministic_fallback"
                decision_reason_code = "autocomplete_agent_unavailable"
                decision_reason = (
                    "Gemini autocomplete agent không được cấu hình; "
                    "giữ nguyên tên import để tìm kiếm an toàn"
                )
            else:
                try:
                    decision = await self.autocomplete_agent.decide(
                        imported_name=disease_name,
                        suggestions=suggestions,
                    )
                    decision_confidence = decision.confidence
                    decision_reason_code = decision.reason_code
                    decision_reason = decision.reason
                    chosen = tuple(
                        value
                        for value in suggestions
                        if value.candidate_id
                        in decision.selected_candidate_ids
                    )
                    if chosen and (
                        decision.reason_code == "ambiguous"
                        or decision.confidence >= 0.60
                    ):
                        selected_suggestions = tuple(
                            value.label for value in chosen
                        )
                        resolved_suggestions = (
                            self.resolve_autocomplete_labels(
                                selected_suggestions
                            )
                        )
                        submitted_query = resolved_suggestions[0]
                        decision_source = "gemini"
                        await search.fill(submitted_query)
                    else:
                        decision_source = "deterministic_fallback"
                except (CrawlerError, ValueError):
                    decision_source = "deterministic_fallback"
                    decision_reason_code = "autocomplete_agent_failed"
                    decision_reason = (
                        "Gemini autocomplete agent không trả về quyết định "
                        "hợp lệ; giữ nguyên tên import để tìm kiếm an toàn"
                    )
            steps.append(
                f"Autocomplete: {decision_source}; "
                f"chọn {len(selected_suggestions)} gợi ý: "
                f"{', '.join(selected_suggestions)}"
                if selected_suggestions
                else (
                    f"Autocomplete: {decision_source}; "
                    "không chọn gợi ý, giữ nguyên tên import"
                )
            )
            if selected_suggestions:
                steps.append(
                    "Tên chuẩn dùng để tìm kiếm: "
                    + ", ".join(resolved_suggestions)
                )
        else:
            decision_reason_code = "autocomplete_no_suggestions"
            decision_reason = "Website không trả về gợi ý autocomplete"
            steps.append("Website không trả về gợi ý autocomplete")
        await search.press("Escape")
        try:
            async with page.expect_navigation(
                wait_until="domcontentloaded",
                timeout=self.plugin.navigation_timeout_ms,
            ):
                await search.press("Enter")
        except PlaywrightTimeoutError:
            return SearchOutcome(
                page.url,
                "search_navigation_timeout",
                "Form tìm kiếm không chuyển sang trang kết quả trong thời hạn",
                tuple(steps),
            )
        steps.append("Đã submit form GET và nhận trang search_result.htm")
        return SearchOutcome(
            page.url,
            None,
            None,
            tuple(steps),
            submitted_query=submitted_query,
            suggestions=suggestions,
            selected_suggestions=selected_suggestions,
            resolved_suggestions=resolved_suggestions,
            decision_source=decision_source,
            decision_confidence=decision_confidence,
            decision_reason_code=decision_reason_code,
            decision_reason=decision_reason,
            result_html=await page.content(),
        )

    async def _search_variants(
        self,
        page: Page,
        disease_name: str,
    ) -> tuple[SearchOutcome, ...]:
        primary = await self._search(page, disease_name)
        if primary.reason_code is not None:
            return (primary,)
        variants = [primary]
        for selected_name in primary.resolved_suggestions[1:10]:
            variants.append(
                await self._submit_search_query(
                    page,
                    selected_name,
                    primary=primary,
                )
            )
        return tuple(variants)

    async def _submit_search_query(
        self,
        page: Page,
        query: str,
        *,
        primary: SearchOutcome,
    ) -> SearchOutcome:
        search = page.locator("#searchTerm")
        if not await search.count():
            await page.goto(
                self.plugin.base_url,
                wait_until="domcontentloaded",
                timeout=self.plugin.navigation_timeout_ms,
            )
            search = page.locator("#searchTerm")
        if not await search.count():
            return SearchOutcome(
                page.url,
                "search_input_not_found",
                "Không tìm thấy ô tìm kiếm cho gợi ý bổ sung",
                (f"Không thể tìm riêng gợi ý: {query}",),
                submitted_query=query,
                suggestions=primary.suggestions,
                selected_suggestions=primary.selected_suggestions,
                resolved_suggestions=primary.resolved_suggestions,
                decision_source=primary.decision_source,
                decision_confidence=primary.decision_confidence,
                decision_reason_code=primary.decision_reason_code,
                decision_reason=primary.decision_reason,
            )
        await search.fill(query)
        await search.press("Escape")
        try:
            async with page.expect_navigation(
                wait_until="domcontentloaded",
                timeout=self.plugin.navigation_timeout_ms,
            ):
                await search.press("Enter")
        except PlaywrightTimeoutError:
            return SearchOutcome(
                page.url,
                "search_navigation_timeout",
                "Gợi ý bổ sung không mở được trang kết quả",
                (f"Search timeout cho gợi ý: {query}",),
                submitted_query=query,
                suggestions=primary.suggestions,
                selected_suggestions=primary.selected_suggestions,
                resolved_suggestions=primary.resolved_suggestions,
                decision_source=primary.decision_source,
                decision_confidence=primary.decision_confidence,
                decision_reason_code=primary.decision_reason_code,
                decision_reason=primary.decision_reason,
            )
        return SearchOutcome(
            page.url,
            None,
            None,
            (f"Đã tìm riêng gợi ý bổ sung: {query}",),
            submitted_query=query,
            suggestions=primary.suggestions,
            selected_suggestions=primary.selected_suggestions,
            resolved_suggestions=primary.resolved_suggestions,
            decision_source=primary.decision_source,
            decision_confidence=primary.decision_confidence,
            decision_reason_code=primary.decision_reason_code,
            decision_reason=primary.decision_reason,
            result_html=await page.content(),
        )

    async def _collect_autocomplete_suggestions(
        self,
        page: Page,
    ) -> tuple[AutocompleteSuggestion, ...]:
        menu = page.locator("ul.ui-autocomplete:visible").last
        try:
            await menu.wait_for(state="visible", timeout=2_500)
        except PlaywrightTimeoutError:
            return ()
        values: list[AutocompleteSuggestion] = []
        seen: set[str] = set()
        entries = menu.locator("li")
        for index in range(min(await entries.count(), 20)):
            label = " ".join((await entries.nth(index).inner_text()).split())
            identity = normalize_search_name(label)
            if not label or identity in seen:
                continue
            seen.add(identity)
            values.append(
                AutocompleteSuggestion(
                    candidate_id=f"autocomplete-{index + 1}",
                    label=label,
                )
            )
        return tuple(values)

    @staticmethod
    def resolve_autocomplete_labels(
        labels: tuple[str, ...],
    ) -> tuple[str, ...]:
        resolved: list[str] = []
        seen: set[str] = set()
        for label in labels:
            parts = autocomplete_label_parts(label)
            value = parts[-1] if parts else " ".join(label.split())
            identity = normalize_search_name(value)
            if not value or identity in seen:
                continue
            seen.add(identity)
            resolved.append(value)
        return tuple(resolved)

    async def _confirm_detail(
        self,
        page: Page,
        candidate: DiscoveredItem,
    ) -> ConfirmationOutcome:
        try:
            await self.plugin.navigate_to_candidate(
                page,
                NavigationCandidate(
                    key=str(candidate.canonical_url),
                    action="goto",
                    target=str(candidate.canonical_url),
                    label=candidate.title_hint,
                    url=candidate.canonical_url,
                ),
            )
            await self.plugin.dismiss_known_popups(page)
            classification = await self.plugin.classify_page(page)
            first_step = (
                f"Detector lần 1: {classification.page_type.value} "
                f"(confidence={classification.confidence:.2f})"
            )
            if classification.page_type is not PageType.DISEASE_DETAIL:
                return ConfirmationOutcome(
                    False,
                    "candidate_not_disease_detail",
                    "Kết quả khớp tên nhưng detector không xác nhận là trang bệnh",
                    (first_step,),
                )
            await self.plugin.wait_for_detail_content(page)
            stable = await self.plugin.classify_page(page)
        except CrawlerError as exc:
            return ConfirmationOutcome(
                False,
                exc.code.value.lower(),
                "Không thể xác nhận nội dung ổn định của trang ứng viên",
                ("Detector hoặc bước chờ nội dung trả về lỗi có kiểm soát",),
            )
        second_step = (
            f"Detector lần 2: {stable.page_type.value} "
            f"(confidence={stable.confidence:.2f})"
        )
        if stable.page_type is not PageType.DISEASE_DETAIL:
            return ConfirmationOutcome(
                False,
                "candidate_not_stable_disease_detail",
                "Trang ứng viên không giữ trạng thái disease detail ổn định",
                (first_step, second_step),
            )
        return ConfirmationOutcome(
            True,
            "disease_detail_confirmed",
            "Khớp tên chính xác và detector xác nhận disease detail hai lần",
            (first_step, second_step),
        )

    def select_exact_candidate(
        self,
        html: str,
        *,
        query: str,
        result_page: str,
    ) -> DiscoveredItem | None:
        return self.analyze_exact_candidates(
            html,
            query=query,
            result_page=result_page,
        ).candidate

    def analyze_exact_candidates(
        self,
        html: str,
        *,
        query: str,
        result_page: str,
    ) -> CandidateScan:
        query_identity = self._name_identity(query)
        candidates: dict[str, DiscoveredItem] = {}
        soup = BeautifulSoup(html, "lxml")
        links = soup.select("a[href]")
        exact_matches = 0
        alias_match_found = False
        for link in links:
            label = " ".join(link.get_text(" ", strip=True).split())
            exact = self._name_identity(label) == query_identity
            alias = is_exact_alias_match(query, label)
            if not exact and not alias:
                continue
            alias_match_found = alias_match_found or alias
            exact_matches += 1
            href = str(link.get("href") or "").strip()
            if not href:
                continue
            target = self.plugin.canonicalize_url(
                urljoin(result_page, href)
            )
            if (
                not self.plugin._is_allowed_url(target)
                or target == self.plugin.canonicalize_url(result_page)
            ):
                continue
            item = DiscoveredItem(
                item_id=build_item_id(self.plugin.name, target),
                source_url=target,
                canonical_url=target,
                title_hint=(
                    autocomplete_label_parts(label)[-1]
                    if alias
                    else label
                ),
                discovery_page=result_page,
            )
            candidates[target] = item
        if not candidates:
            return CandidateScan(None, len(links), exact_matches, None)
        return CandidateScan(
            candidates[sorted(candidates)[0]],
            len(links),
            exact_matches,
            "alias_exact" if alias_match_found else "exact_normalized",
        )

    def _search_candidates(
        self,
        html: str,
        *,
        result_page: str,
    ) -> tuple[tuple[SearchCandidate, ...], int]:
        soup = BeautifulSoup(html, "lxml")
        links = soup.select("a[href]")
        candidates: list[SearchCandidate] = []
        for link in links:
            label = " ".join(link.get_text(" ", strip=True).split())
            for suffix in (" es", " s"):
                if label.casefold().endswith(suffix):
                    label = f"{label[: -len(suffix)]}{suffix.strip()}"
                    break
            href = str(link.get("href") or "").strip()
            if not label or not href:
                continue
            candidates.append(
                SearchCandidate(
                    label,
                    self.plugin.canonicalize_url(
                        urljoin(result_page, href)
                    ),
                )
            )
        return tuple(candidates), len(links)

    def _persist_category_expansion(
        self,
        job_id: str,
        result: CategoryExpansionResult,
    ) -> None:
        self.artifacts.persist_category_expansion(
            job_id,
            {
                "schema_version": "1.0",
                "job_id": job_id,
                "visited_count": result.visited_count,
                "confirmed_disease_count": len(result.items),
                "stopped_reason": result.stopped_reason,
                "limits_reached": list(result.limits_reached),
                "nodes": [
                    {
                        "root_query": node.root_query,
                        "label": node.label,
                        "url": str(node.url),
                        "canonical_url": str(node.canonical_url),
                        "parent_url": (
                            str(node.parent_url)
                            if node.parent_url is not None
                            else None
                        ),
                        "menu_path": list(node.menu_path),
                        "depth": node.depth,
                        "page_type": node.page_type.value,
                        "confidence": node.confidence,
                        "status": node.status.value,
                        "reason_code": node.reason_code.value,
                        "reason": self._category_reason(
                            node.reason_code.value
                        ),
                        "action_steps": list(
                            self._category_actions(
                                node.reason_code.value
                            )
                        ),
                    }
                    for node in result.nodes
                ],
                "provenance": [
                    {
                        "item_id": value.item_id,
                        "root_query": value.root_query,
                        "parent_url": (
                            str(value.parent_url)
                            if value.parent_url is not None
                            else None
                        ),
                        "menu_path": list(value.menu_path),
                        "depth": value.depth,
                    }
                    for value in result.provenance
                ],
            },
        )

    @staticmethod
    def _category_reason(reason_code: str) -> str:
        try:
            return CATEGORY_REASON_VI[CategoryReasonCode(reason_code)]
        except ValueError:
            return {
                "exact_match": "Đã chọn kết quả khớp chính xác.",
                "candidate_not_category": (
                    "Kết quả số ít/số nhiều không phải menu bệnh."
                ),
                "category_no_confirmed_disease": (
                    "Menu không có trang bệnh con được xác nhận."
                ),
            }.get(reason_code, "Node được ghi lại để kiểm tra.")

    @staticmethod
    def _category_actions(reason_code: str) -> tuple[str, ...]:
        try:
            return CATEGORY_REASON_ACTIONS_VI[
                CategoryReasonCode(reason_code)
            ]
        except ValueError:
            return ("Ghi node vào audit.", "Tiếp tục node kế tiếp.")

    @staticmethod
    def _name_identity(value: str) -> str:
        return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))
