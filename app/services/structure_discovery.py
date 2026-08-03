from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from app.models.coverage import DetectedTable, PageStructureProfile, SiteProfile
from app.models.tabs import RawDiseaseTab

CONTENT_ROOT_SELECTORS = (
    "article",
    "main",
    "#content",
    "[role='main']",
    ".content",
    ".main-content",
    ".genrearticle",
    ".tabContainer",
)


class SiteStructureProfiler:
    """Infer a conservative source contract from a representative detail page."""

    def analyze_page(self, html: str, *, url: str) -> PageStructureProfile:
        soup = BeautifulSoup(html, "lxml")
        parsed_url = urlparse(url)
        roots = tuple(
            selector
            for selector in CONTENT_ROOT_SELECTORS
            if self._has_meaningful_text(soup.select_one(selector))
        )
        headings = tuple(
            sorted(
                {
                    int(node.name[1])
                    for node in soup.find_all(
                        [f"h{level}" for level in range(1, 7)]
                    )
                    if isinstance(node, Tag)
                }
            )
        )
        tables = tuple(
            self._table_profile(table, index)
            for index, table in enumerate(soup.find_all("table"), start=1)
            if isinstance(table, Tag)
        )
        tab_labels = tuple(
            dict.fromkeys(
                label
                for node in soup.select(
                    "[role='tab'], [data-toggle='tab'], [data-bs-toggle='tab'], "
                    "a[href*='tab'], button"
                )
                if (label := self._text(node))
            )
        )
        same_origin_links = {
            absolute
            for node in soup.find_all("a", href=True)
            if (
                (absolute := urljoin(url, str(node.get("href") or "")))
                and urlparse(absolute).scheme in {"http", "https"}
                and urlparse(absolute).netloc.casefold()
                == parsed_url.netloc.casefold()
            )
        }
        dynamic_markers: list[str] = []
        if soup.select_one("[hx-get], [hx-post]") is not None:
            dynamic_markers.append("htmx")
        if soup.select_one("[data-reactroot], #__next, #app, #root") is not None:
            dynamic_markers.append("client_rendered_app")
        if any("ajax" in str(node.get("href") or "").casefold() for node in soup.find_all("a")):
            dynamic_markers.append("ajax_links")
        title = self._text(soup.title) or None
        return PageStructureProfile(
            url=url,
            title=title,
            content_root_candidates=roots,
            heading_levels=headings,
            tables=tables,
            tab_labels=tab_labels,
            form_count=len(soup.find_all("form")),
            same_origin_link_count=len(same_origin_links),
            dynamic_markers=tuple(dynamic_markers),
        )

    def build_profile(
        self,
        *,
        plugin: str,
        html: str,
        url: str,
        tabs: tuple[RawDiseaseTab, ...],
        required_tabs: tuple[str, ...],
    ) -> SiteProfile:
        structure = self.analyze_page(html, url=url)
        captured = tuple(tab.key for tab in tabs if tab.available and tab.html.strip())
        blockers: list[str] = []
        if not structure.content_root_candidates:
            blockers.append("content_root_not_detected")
        for key in required_tabs:
            if key not in captured:
                blockers.append(f"required_tab_missing:{key}")
        parsed = urlparse(url)
        return SiteProfile(
            plugin=plugin,
            domain=parsed.netloc.casefold(),
            representative_url=url,
            structure=structure,
            required_tabs=required_tabs,
            captured_tabs=captured,
            ready=not blockers,
            blockers=tuple(blockers),
        )

    def _table_profile(self, table: Tag, index: int) -> DetectedTable:
        table_id = str(table.get("id") or "").strip()
        selector = f"table#{table_id}" if table_id else f"table:nth-of-type({index})"
        first_row = table.find("tr")
        headers = (
            tuple(self._text(cell) for cell in first_row.find_all(["th", "td"], recursive=False))
            if isinstance(first_row, Tag)
            else ()
        )
        return DetectedTable(
            selector=selector,
            headers=tuple(value for value in headers if value),
            row_count=len(table.find_all("tr")),
        )

    @staticmethod
    def _text(node: Tag | None) -> str:
        return " ".join(node.get_text(" ", strip=True).split()) if node else ""

    def _has_meaningful_text(self, node: Tag | None) -> bool:
        return len(self._text(node)) >= 50
