import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Locator, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.core.config import Credentials
from app.core.errors import CrawlerError, ErrorCode
from app.core.ids import build_item_id
from app.models.discovery import DiscoveredItem, DiscoveryCandidate
from app.models.navigation import NavigationCandidate, PageClassification, PageType
from app.models.tabs import RawDiseaseTab, RawTabRelatedDetail, TabKey
from app.plugins.base import SitePlugin
from app.plugins.genre_manuals import selectors

DETAIL_URL_PATTERN = re.compile(
    r"(?:/(?:[a-z]{2}_)?(?:med|medical|disease)_[^/?#]+\.html?"
    r"|/diseases?/[^/?#]+/?)$",
    re.IGNORECASE,
)
MEDICAL_SECTION_TERMS = frozenset(
    {
        "cause",
        "causes",
        "diagnosis",
        "prognosis",
        "risk factor",
        "risk factors",
        "signs and symptoms",
        "symptoms",
        "treatment",
    }
)
CONTENT_CANDIDATE_TERMS = frozenset(
    {
        "disease",
        "diseases",
        "medical",
        "medicine",
        "conditions",
    }
)
EXCLUDED_DISCOVERY_TERMS = frozenset(
    {
        "calculator",
        "copyright",
        "financial",
        "history",
        "hobbies",
        "imprint",
        "logout",
        "occupation",
        "privacy",
        "questionnaire",
        "rating-sheet",
        "travel",
        "user-settings",
    }
)


class GenreManualsPlugin(SitePlugin):
    name = "genre_manuals"
    allowed_domains = frozenset({"www.genre-manuals.com", "genre-manuals.com"})

    def __init__(
        self,
        *,
        base_url: str,
        navigation_timeout_ms: int = 30_000,
        selector_timeout_ms: int = 10_000,
        detail_confidence_threshold: float = 0.80,
        minimum_detail_chars: int = 250,
    ) -> None:
        self.base_url = base_url
        self.navigation_timeout_ms = navigation_timeout_ms
        self.selector_timeout_ms = selector_timeout_ms
        self.detail_confidence_threshold = detail_confidence_threshold
        self.minimum_detail_chars = minimum_detail_chars

    async def discover_demo_items(self) -> list[DiscoveredItem]:
        return []

    def raw_tabs_complete(self, tabs: tuple[RawDiseaseTab, ...]) -> bool:
        required = {"info", "life_dd_tpd", "ip", "health"}
        return {tab.key for tab in tabs} == required and all(
            tab.available and bool(tab.html.strip()) for tab in tabs
        )

    async def discover_items(self, page: Page) -> list[DiscoveredItem]:
        self._validate_allowed_url(page.url)
        branch_links = await self._current_tree_sibling_links(page)
        breadcrumb = (await self._first_inner_text(page, selectors.BREADCRUMB)).lower()
        if "medical" not in breadcrumb or "ratings" not in breadcrumb:
            branch_links = None
        links = branch_links or page.locator(selectors.NAVIGATION_LINKS)
        items: dict[str, DiscoveredItem] = {}
        for index in range(await links.count()):
            link = links.nth(index)
            href = await link.get_attribute("href")
            if not href:
                continue
            source_url = urljoin(page.url, href)
            if not self._is_allowed_url(source_url):
                continue
            canonical_url = self.canonicalize_url(source_url)
            if canonical_url == self.canonicalize_url(page.url):
                continue
            if branch_links is None and not DETAIL_URL_PATTERN.search(urlparse(canonical_url).path):
                continue
            title = " ".join((await link.inner_text()).split()) or None
            item_id = build_item_id(self.name, canonical_url)
            items[item_id] = DiscoveredItem(
                item_id=item_id,
                source_url=source_url,
                canonical_url=canonical_url,
                title_hint=title,
                discovery_page=page.url,
            )
        return sorted(items.values(), key=lambda item: str(item.canonical_url))

    async def find_next_listing_page(
        self,
        page: Page,
        visited_pages: frozenset[str],
    ) -> NavigationCandidate | None:
        links = page.locator(selectors.NEXT_PAGE)
        for index in range(await links.count()):
            link = links.nth(index)
            href = await link.get_attribute("href")
            if not href:
                continue
            absolute_url = self.canonicalize_url(urljoin(page.url, href))
            if not self._is_allowed_url(absolute_url) or absolute_url in visited_pages:
                continue
            return NavigationCandidate(
                key=absolute_url,
                action="goto",
                target=absolute_url,
                label="next_page",
                url=absolute_url,
            )
        return None

    async def discover_search_candidates(
        self,
        page: Page,
        visited_urls: frozenset[str],
    ) -> list[DiscoveryCandidate]:
        """Rank links that can lead to additional disease-detail pages.

        The live site only expands one branch of its medical tree at a time.
        Visiting category pages is therefore required to reveal more diseases.
        """
        self._validate_allowed_url(page.url)
        links = await self._medical_ratings_links(page)
        if links is None:
            links = page.locator(selectors.NAVIGATION_LINKS)

        current_url = self.canonicalize_url(page.url)
        candidates: dict[str, DiscoveryCandidate] = {}
        for index in range(await links.count()):
            link = links.nth(index)
            href = await link.get_attribute("href")
            if not href:
                continue
            absolute_url = self.canonicalize_url(urljoin(page.url, href))
            if (
                not self._is_allowed_url(absolute_url)
                or absolute_url == current_url
                or absolute_url in visited_urls
            ):
                continue
            label = " ".join((await link.inner_text()).split()) or None
            score = self._discovery_candidate_score(absolute_url, label)
            if score <= 0:
                continue
            candidate = DiscoveryCandidate(
                url=absolute_url,
                label=label,
                score=score,
                source_url=current_url,
            )
            previous = candidates.get(absolute_url)
            if previous is None or candidate.score > previous.score:
                candidates[absolute_url] = candidate
        return sorted(
            candidates.values(),
            key=lambda candidate: (-candidate.score, str(candidate.url)),
        )

    def canonicalize_url(self, url: str) -> str:
        parsed = urlparse(url)
        query = urlencode(
            sorted(
                (key, value)
                for key, value in parse_qsl(parsed.query, keep_blank_values=True)
                if not key.lower().startswith("utm_")
            )
        )
        path = parsed.path or "/"
        if path != "/" and path.endswith("/"):
            path = path.rstrip("/")
        return urlunparse(
            (
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                path,
                "",
                query,
                "",
            )
        )

    async def validate_session(self, page: Page) -> bool:
        response = await page.goto(
            self.base_url,
            wait_until="domcontentloaded",
            timeout=self.navigation_timeout_ms,
        )
        if response is not None and response.status >= 400:
            raise CrawlerError(
                ErrorCode.NAVIGATION_FAILED,
                f"Session validation page returned HTTP {response.status}",
            )
        self._validate_allowed_url(page.url)
        return await self._is_authenticated_page(page)

    async def login(self, page: Page, credentials: Credentials) -> None:
        response = await page.goto(
            self.base_url,
            wait_until="domcontentloaded",
            timeout=self.navigation_timeout_ms,
        )
        if response is not None and response.status >= 400:
            raise CrawlerError(
                ErrorCode.NAVIGATION_FAILED,
                f"Login page returned HTTP {response.status}",
            )
        self._validate_allowed_url(page.url)

        if await self._is_authenticated_page(page):
            return
        if await page.locator(selectors.MFA_OR_CAPTCHA).count():
            raise CrawlerError(
                ErrorCode.AUTH_MFA_OR_CAPTCHA,
                "Login requires operator action for MFA or CAPTCHA",
            )
        if not await page.locator(selectors.LOGIN_FORM).count():
            raise CrawlerError(
                ErrorCode.AUTH_FORM_NOT_FOUND,
                "Expected login form was not found",
            )

        await page.locator(selectors.USERNAME_INPUT).fill(credentials.username.get_secret_value())
        await page.locator(selectors.PASSWORD_INPUT).fill(credentials.password.get_secret_value())
        remember_me = page.locator(selectors.REMEMBER_ME)
        if await remember_me.count() and not await remember_me.is_checked():
            await remember_me.check()

        try:
            await page.locator(selectors.SUBMIT).click(timeout=self.selector_timeout_ms)
            await page.wait_for_load_state(
                "domcontentloaded",
                timeout=self.navigation_timeout_ms,
            )
        except PlaywrightTimeoutError as exc:
            raise CrawlerError(
                ErrorCode.NETWORK_TIMEOUT,
                "Login navigation timed out",
            ) from exc

        self._validate_allowed_url(page.url)
        if await page.locator(selectors.MFA_OR_CAPTCHA).count():
            raise CrawlerError(
                ErrorCode.AUTH_MFA_OR_CAPTCHA,
                "Login requires operator action for MFA or CAPTCHA",
            )
        if await page.locator(selectors.LOGIN_FORM).count():
            raise CrawlerError(
                ErrorCode.AUTH_INVALID_CREDENTIALS,
                "Login was rejected",
            )
        if not await self._is_authenticated_page(page):
            raise CrawlerError(
                ErrorCode.AUTH_SESSION_EXPIRED,
                "Login completed without an authenticated session marker",
            )

    async def dismiss_known_popups(self, page: Page) -> int:
        dismissed = 0
        for selector in selectors.KNOWN_POPUP_CLOSE.split(", "):
            locator = page.locator(selector)
            if not await locator.count():
                continue
            try:
                await locator.first.click(timeout=self.selector_timeout_ms)
                dismissed += 1
            except PlaywrightTimeoutError:
                continue
        return dismissed

    async def classify_page(self, page: Page) -> PageClassification:
        self._validate_allowed_url(page.url)
        if await page.locator(selectors.LOGIN_FORM).count():
            return self._classification(
                page.url,
                PageType.LOGIN,
                1,
                ("login_form",),
                "",
            )
        if await page.locator(selectors.BLOCKED_OR_CAPTCHA).count():
            return self._classification(
                page.url,
                PageType.BLOCKED_OR_CAPTCHA,
                1,
                ("blocked_or_captcha_marker",),
                "",
            )

        title = await self._first_inner_text(page, selectors.PAGE_TITLE)
        content = await self._combined_inner_text(page, selectors.CONTENT_ROOT)
        breadcrumb = await self._first_inner_text(page, selectors.BREADCRUMB)
        normalized_breadcrumb = " ".join(breadcrumb.lower().split())
        is_medical_ratings = (
            "medical" in normalized_breadcrumb and "ratings" in normalized_breadcrumb
        )
        normalized_text = " ".join(f"{title} {content}".lower().split())
        matched_terms = tuple(
            sorted(term for term in MEDICAL_SECTION_TERMS if term in normalized_text)
        )
        signals: list[str] = []
        score = 0.0

        branch_links = await self._current_tree_branch_links(page)
        branch_link_count = await branch_links.count() if branch_links else 0
        if is_medical_ratings and branch_link_count > 1:
            return self._classification(
                page.url,
                PageType.DISEASE_LIST,
                min(0.75 + branch_link_count * 0.01, 0.95),
                (
                    "medical_ratings_breadcrumb",
                    f"active_branch_links:{branch_link_count - 1}",
                ),
                f"{title}\n{breadcrumb}",
            )

        if DETAIL_URL_PATTERN.search(urlparse(page.url).path):
            score += 0.35
            signals.append("detail_url_pattern")
        if is_medical_ratings:
            score += 0.35
            signals.append("medical_ratings_breadcrumb")
        if title.strip():
            score += 0.20
            signals.append("page_title")
        if len(content.strip()) >= self.minimum_detail_chars:
            score += 0.30
            signals.append("content_root_min_length")
        if matched_terms:
            score += 0.15
            signals.append(f"medical_sections:{','.join(matched_terms)}")
        if (
            score >= self.detail_confidence_threshold
            and title.strip()
            and len(content.strip()) >= self.minimum_detail_chars
        ):
            return self._classification(
                page.url,
                PageType.DISEASE_DETAIL,
                score,
                tuple(signals),
                f"{title}\n{content[:500]}",
            )

        detail_link_count = await self._detail_link_count(page)
        if detail_link_count:
            return self._classification(
                page.url,
                PageType.DISEASE_LIST,
                min(0.70 + detail_link_count * 0.05, 0.95),
                (f"detail_links:{detail_link_count}",),
                title,
            )

        candidate = await self.find_next_content_candidate(page, frozenset())
        if candidate is not None:
            return self._classification(
                page.url,
                PageType.HOME_OR_MENU,
                0.80,
                ("content_navigation_candidate",),
                title,
            )

        unknown_signals = tuple(signals) if signals else ("no_known_page_signals",)
        return self._classification(
            page.url,
            PageType.UNKNOWN,
            min(score, 0.60),
            unknown_signals,
            f"{title}\n{content[:500]}",
        )

    async def find_next_content_candidate(
        self,
        page: Page,
        visited: frozenset[str],
    ) -> NavigationCandidate | None:
        branch_links = await self._current_tree_branch_links(page)
        links = branch_links or page.locator("a[href]")
        breadcrumb = (await self._first_inner_text(page, selectors.BREADCRUMB)).lower()
        in_medical_tree = "medical" in breadcrumb
        ranked: list[tuple[int, str, str]] = []
        for index in range(await links.count()):
            link = links.nth(index)
            href = await link.get_attribute("href")
            if not href:
                continue
            absolute_url = urljoin(page.url, href)
            if not self._is_allowed_url(absolute_url):
                continue
            parsed_path = urlparse(absolute_url).path.lower()
            if any(term in parsed_path for term in ("/logout", "privacy", "imprint")):
                continue
            label = " ".join((await link.inner_text()).split())
            normalized_label = label.lower()
            score = 0
            if DETAIL_URL_PATTERN.search(parsed_path):
                score = 100
            elif normalized_label == "ratings" and in_medical_tree:
                score = 95
            elif normalized_label.rstrip(" »") == "medical":
                score = 90
            elif branch_links is not None:
                score = 85
            elif "/medical" in parsed_path or "_med_" in parsed_path:
                score = 80
            elif any(term in normalized_label for term in CONTENT_CANDIDATE_TERMS):
                score = 70
            if not score or absolute_url in visited or absolute_url == page.url:
                continue
            ranked.append((score, absolute_url, label))

        if not ranked:
            return None
        _, url, label = sorted(ranked, key=lambda item: (-item[0], item[1]))[0]
        return NavigationCandidate(
            key=url,
            action="goto",
            target=url,
            label=label or None,
            url=url,
        )

    async def navigate_to_candidate(
        self,
        page: Page,
        candidate: NavigationCandidate,
    ) -> None:
        try:
            if candidate.action == "goto":
                response = await page.goto(
                    candidate.target,
                    wait_until="domcontentloaded",
                    timeout=self.navigation_timeout_ms,
                )
                if response is not None and response.status >= 400:
                    raise CrawlerError(
                        ErrorCode.NAVIGATION_FAILED,
                        f"Candidate page returned HTTP {response.status}",
                    )
            else:
                await page.locator(candidate.target).click(timeout=self.selector_timeout_ms)
                await page.wait_for_load_state(
                    "domcontentloaded",
                    timeout=self.navigation_timeout_ms,
                )
        except PlaywrightTimeoutError as exc:
            raise CrawlerError(
                ErrorCode.NETWORK_TIMEOUT,
                "Candidate navigation timed out",
            ) from exc
        self._validate_allowed_url(page.url)

    async def wait_for_detail_content(self, page: Page) -> None:
        try:
            await page.wait_for_function(
                """
                ([selector, minimumChars]) => {
                    const text = [...document.querySelectorAll(selector)]
                        .map(node => node.innerText || "")
                        .join("\\n")
                        .trim();
                    return text.length >= minimumChars;
                }
                """,
                arg=[selectors.CONTENT_ROOT, self.minimum_detail_chars],
                timeout=self.selector_timeout_ms,
            )
        except PlaywrightTimeoutError as exc:
            raise CrawlerError(
                ErrorCode.CONTENT_EMPTY,
                "Disease detail content did not become ready",
            ) from exc

    async def screenshot_masks(self, page: Page) -> list[Locator]:
        account_region = page.locator("#genre-shortcuts")
        if await account_region.count():
            return [account_region.first]
        logout = page.locator("a[href*='logout' i]")
        if not await logout.count():
            return []
        account_list = logout.first.locator("xpath=ancestor::ul[1]")
        return [account_list] if await account_list.count() else [logout.first]

    async def capture_detail_tabs(
        self,
        page: Page,
    ) -> tuple[RawDiseaseTab, ...]:
        tab_container = page.locator(".tabContainer").first
        tab_links = page.locator("ul.idTabs a")
        if not await tab_container.count() or not await tab_links.count():
            raise CrawlerError(
                ErrorCode.CONTENT_EMPTY,
                "Disease detail is missing the required tab container",
            )

        definitions: tuple[tuple[TabKey, str], ...] = (
            ("info", "Info"),
            ("life_dd_tpd", "Life/DD/TPD"),
            ("ip", "IP"),
            ("health", "Health"),
        )
        info_html = await tab_container.inner_html()
        if not info_html.strip():
            raise CrawlerError(
                ErrorCode.CONTENT_EMPTY,
                "Disease Info tab is empty",
            )
        captured: list[RawDiseaseTab] = [
            RawDiseaseTab(
                key="info",
                label="Info",
                source_url=page.url,
                html=info_html,
            )
        ]
        for key, label in definitions[1:]:
            link = tab_links.filter(has_text=label).first
            if not await link.count():
                raise CrawlerError(
                    ErrorCode.CONTENT_EMPTY,
                    f"Disease detail is missing the required {label} tab",
                )
            onclick = await link.get_attribute("onclick") or ""
            endpoint_match = re.search(
                r"['\"]([^'\"]+\.html\.ajax)['\"]",
                onclick,
            )
            source_url = urljoin(page.url, endpoint_match.group(1)) if endpoint_match else page.url
            html = await self._capture_required_tab_html(
                page,
                link=link,
                label=label,
                source_url=source_url,
            )
            captured.append(
                RawDiseaseTab(
                    key=key,
                    label=label,
                    source_url=source_url,
                    html=html,
                )
            )
        enriched: list[RawDiseaseTab] = []
        for tab in captured:
            enriched.append(await self._capture_related_details(page, tab))
        return tuple(enriched)

    async def _capture_required_tab_html(
        self,
        page: Page,
        *,
        link: Locator,
        label: str,
        source_url: str,
    ) -> str:
        for _ in range(3):
            previous_html = await page.locator(".tabContainer").first.inner_html()
            try:
                async with page.expect_response(
                    lambda response: ".html.ajax" in response.url,
                    timeout=self.selector_timeout_ms,
                ):
                    await link.click(timeout=self.selector_timeout_ms)
                html = await page.locator(".tabContainer").first.inner_html()
                if html.strip() and html != previous_html:
                    return html
            except PlaywrightTimeoutError:
                html = await page.locator(".tabContainer").first.inner_html()
                if html.strip() and html != previous_html:
                    return html

            if source_url != page.url:
                try:
                    response = await page.context.request.get(
                        source_url,
                        headers={"Referer": page.url},
                        timeout=self.navigation_timeout_ms,
                    )
                    if response.status < 400:
                        html = await response.text()
                        if len(BeautifulSoup(html, "lxml").get_text(strip=True)) >= 1:
                            return html
                except PlaywrightError:
                    pass

        raise CrawlerError(
            ErrorCode.CONTENT_EMPTY,
            f"Required {label} tab could not be captured after retries",
        )

    async def _capture_related_details(
        self,
        page: Page,
        tab: RawDiseaseTab,
    ) -> RawDiseaseTab:
        if not tab.available or not tab.html:
            return tab
        details: list[RawTabRelatedDetail] = []
        for target, label in self._related_detail_targets(
            tab.html,
            base_url=page.url,
        ):
            try:
                response = await page.context.request.get(
                    target,
                    timeout=self.navigation_timeout_ms,
                )
                if response.status >= 400:
                    details.append(
                        RawTabRelatedDetail(
                            label=label,
                            url=target,
                            available=False,
                            warning=f"related_http_{response.status}",
                        )
                    )
                    continue
                html = self._related_content_fragment(await response.text())
                if not html:
                    details.append(
                        RawTabRelatedDetail(
                            label=label,
                            url=target,
                            available=False,
                            warning="related_content_root_not_found",
                        )
                    )
                    continue
            except PlaywrightError:
                details.append(
                    RawTabRelatedDetail(
                        label=label,
                        url=target,
                        available=False,
                        warning="related_fetch_failed",
                    )
                )
                continue
            details.append(
                RawTabRelatedDetail(
                    label=label,
                    url=target,
                    html=html,
                )
            )
        return tab.model_copy(update={"related_details": tuple(details)})

    def _related_detail_targets(
        self,
        tab_html: str,
        *,
        base_url: str,
    ) -> tuple[tuple[str, str], ...]:
        """Return unique read-only popup targets; never include edit/cart actions."""
        soup = BeautifulSoup(tab_html, "lxml")
        targets: dict[str, str] = {}
        for link in soup.select("a.genrePopup[href]"):
            label = " ".join(link.get_text(" ", strip=True).split())
            href = str(link.get("href") or "").strip()
            normalized_label = label.casefold()
            if (
                not label
                or not href
                or normalized_label in {"edit", "edit note", "+"}
                or "edit" in normalized_label
            ):
                continue
            target = self.canonicalize_url(urljoin(base_url, href))
            if not self._is_allowed_url(target):
                continue
            targets.setdefault(target, label)
        return tuple(targets.items())

    @staticmethod
    def _related_content_fragment(html: str) -> str:
        """Keep article content only, excluding account/navigation chrome."""
        soup = BeautifulSoup(html, "lxml")
        roots = soup.select(".genrearticle")
        if not roots:
            return ""
        title = soup.select_one("h2.pageTitle, h1, #content h2")
        title_html = str(title) if title is not None else ""
        return f"<article>{title_html}{''.join(str(root) for root in roots)}</article>"

    def content_root_selectors(self) -> tuple[str, ...]:
        return (".genrearticle",)

    def content_title_selectors(self) -> tuple[str, ...]:
        return ("h2.pageTitle", "h1", "#content h2")

    async def _is_authenticated_page(self, page: Page) -> bool:
        if await page.locator(selectors.LOGIN_FORM).count():
            return False
        return bool(await page.locator(selectors.AUTHENTICATED_CONTENT).count())

    def _validate_allowed_url(self, url: str) -> None:
        if not self._is_allowed_url(url):
            raise CrawlerError(
                ErrorCode.NAVIGATION_FAILED,
                "Navigation left the plugin allowlisted domain",
            )

    def _is_allowed_url(self, url: str) -> bool:
        parsed = urlparse(url)
        return parsed.scheme in {"http", "https"} and parsed.hostname in self.allowed_domains

    async def _first_inner_text(self, page: Page, selector: str) -> str:
        locator = page.locator(selector)
        if not await locator.count():
            return ""
        return await locator.first.inner_text()

    async def _combined_inner_text(self, page: Page, selector: str) -> str:
        locator = page.locator(selector)
        texts: list[str] = []
        for index in range(await locator.count()):
            texts.append(await locator.nth(index).inner_text())
        return "\n".join(texts)

    async def _current_tree_branch_links(self, page: Page) -> Locator | None:
        links = page.locator("#sidemenutree a[href]")
        current_url = self.canonicalize_url(page.url)
        for index in range(await links.count()):
            link = links.nth(index)
            href = await link.get_attribute("href")
            if not href:
                continue
            if self.canonicalize_url(urljoin(page.url, href)) != current_url:
                continue
            if not hasattr(link, "locator"):
                continue
            branch = link.locator("xpath=ancestor::li[1]")
            if not await branch.count():
                continue
            branch_links = branch.locator("a[href]")
            if await branch_links.count():
                return branch_links
        return None

    async def _current_tree_sibling_links(self, page: Page) -> Locator | None:
        links = page.locator("#sidemenutree a[href]")
        current_url = self.canonicalize_url(page.url)
        for index in range(await links.count()):
            link = links.nth(index)
            href = await link.get_attribute("href")
            if not href:
                continue
            if self.canonicalize_url(urljoin(page.url, href)) != current_url:
                continue
            if not hasattr(link, "locator"):
                continue
            sibling_list = link.locator("xpath=ancestor::ul[1]")
            if not await sibling_list.count():
                continue
            sibling_links = sibling_list.locator(":scope > li > a[href]")
            if await sibling_links.count():
                return sibling_links
        return None

    async def _medical_ratings_links(self, page: Page) -> Locator | None:
        links = page.locator("#sidemenutree a[href]")
        for index in range(await links.count()):
            link = links.nth(index)
            label = " ".join((await link.inner_text()).lower().split())
            if label != "ratings":
                continue
            branch = link.locator("xpath=ancestor::li[1]")
            if await branch.count():
                return branch.locator("a[href]")
        return None

    def _discovery_candidate_score(self, url: str, label: str | None) -> int:
        parsed = urlparse(url)
        path = parsed.path.lower()
        normalized_label = (label or "").lower()
        combined = f"{path} {normalized_label}"
        if any(term in combined for term in EXCLUDED_DISCOVERY_TERMS):
            return 0
        if parsed.query or parsed.fragment:
            return 0
        if re.search(r"/(?:en_)?[^/]+\.html?$", path):
            return 95 if path.startswith("/en_") else 88
        if path.startswith("/en_"):
            return 92
        if "/sites/clue/home/page7/page8/" in path:
            return 82
        if path.endswith("/page8.html"):
            return 78
        if any(term in combined for term in CONTENT_CANDIDATE_TERMS):
            return 72
        return 0

    async def _detail_link_count(self, page: Page) -> int:
        links = page.locator(selectors.NAVIGATION_LINKS)
        count = 0
        for index in range(await links.count()):
            href = await links.nth(index).get_attribute("href")
            if href and DETAIL_URL_PATTERN.search(urlparse(urljoin(page.url, href)).path):
                count += 1
        return count

    def _classification(
        self,
        url: str,
        page_type: PageType,
        confidence: float,
        matched_signals: tuple[str, ...],
        fingerprint_content: str,
    ) -> PageClassification:
        fingerprint_source = "\n".join(
            (
                url,
                page_type.value,
                " ".join(fingerprint_content.lower().split()),
            )
        )
        return PageClassification(
            page_type=page_type,
            confidence=min(confidence, 1),
            matched_signals=matched_signals,
            fingerprint=hashlib.sha256(fingerprint_source.encode()).hexdigest(),
        )
