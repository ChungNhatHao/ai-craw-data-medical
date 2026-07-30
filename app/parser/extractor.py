from dataclasses import dataclass
from html import escape
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag
from trafilatura import extract as trafilatura_extract

from app.core.errors import CrawlerError, ErrorCode

REMOVE_SELECTORS = (
    "script",
    "style",
    "noscript",
    "nav",
    "footer",
    "header",
    "form",
    "aside",
    "#sidemenutree",
    "#genre-shortcuts",
    ".breadcrumb",
    ".breadcrumbs",
    ".pagination",
    ".cookie-banner",
    ".modal",
)
ALLOWED_TAGS = frozenset(
    {
        "a",
        "article",
        "b",
        "blockquote",
        "br",
        "code",
        "div",
        "em",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "i",
        "li",
        "ol",
        "p",
        "pre",
        "span",
        "strong",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "ul",
    }
)


@dataclass(frozen=True)
class ExtractedContent:
    html: str
    plain_text: str
    text_chars: int
    removed_nodes: int = 0
    warnings: tuple[str, ...] = ()


class ContentExtractor:
    def __init__(self, *, minimum_chars: int = 50) -> None:
        self.minimum_chars = minimum_chars

    def extract(
        self,
        raw_html: str,
        *,
        root_selectors: tuple[str, ...],
        title_selectors: tuple[str, ...],
    ) -> ExtractedContent:
        if not raw_html.strip():
            raise CrawlerError(ErrorCode.CONTENT_EMPTY, "Raw HTML is empty")
        soup = BeautifulSoup(raw_html, "lxml")
        removed_nodes = 0
        for selector in REMOVE_SELECTORS:
            for node in soup.select(selector):
                node.decompose()
                removed_nodes += 1

        title = self._first_text(soup, title_selectors)
        roots = self._select_roots(soup, root_selectors)
        warnings: list[str] = []
        if not self._has_minimum_text(roots):
            roots = self._select_roots(soup, ("article", "main", "#content"))
            warnings.append("generic_content_root_fallback")

        if not self._has_minimum_text(roots):
            fallback = trafilatura_extract(
                raw_html,
                output_format="html",
                include_links=True,
                include_tables=True,
                favor_recall=True,
            )
            if fallback:
                fallback_soup = BeautifulSoup(fallback, "lxml")
                roots = [
                    node
                    for node in fallback_soup.select("body")
                    if isinstance(node, Tag)
                ]
                warnings.append("trafilatura_fallback")

        fragments = [str(root) for root in roots]
        content_soup = BeautifulSoup("<article></article>", "lxml")
        article = content_soup.find("article")
        if article is None:
            raise CrawlerError(
                ErrorCode.CONTENT_INVALID,
                "Could not create extracted content container",
            )
        if title:
            title_fragment = BeautifulSoup(
                f"<h1>{escape(title)}</h1>",
                "lxml",
            ).find("h1")
            if title_fragment is not None:
                article.append(title_fragment)
        for fragment in fragments:
            parsed = BeautifulSoup(fragment, "lxml")
            body = parsed.body
            if body is None:
                continue
            for child in list(body.children):
                article.append(child)

        removed_nodes += self._sanitize(article)
        plain_text = self._plain_text(article)
        text_chars = len(plain_text)
        if text_chars < self.minimum_chars:
            raise CrawlerError(
                ErrorCode.CONTENT_EMPTY,
                "Extracted disease content is empty or below minimum length",
            )
        return ExtractedContent(
            html=str(article),
            plain_text=plain_text,
            text_chars=text_chars,
            removed_nodes=removed_nodes,
            warnings=tuple(dict.fromkeys(warnings)),
        )

    def _first_text(
        self,
        soup: BeautifulSoup,
        selectors: tuple[str, ...],
    ) -> str:
        for selector in selectors:
            node = soup.select_one(selector)
            if node is not None:
                text = " ".join(node.get_text(" ", strip=True).split())
                if text:
                    return text
        return ""

    def _select_roots(
        self,
        soup: BeautifulSoup,
        selectors: tuple[str, ...],
    ) -> list[Tag]:
        selected: list[Tag] = []
        for selector in selectors:
            for node in soup.select(selector):
                if not isinstance(node, Tag):
                    continue
                if any(parent in selected for parent in node.parents):
                    continue
                selected.append(node)
        return selected

    def _has_minimum_text(self, roots: list[Tag]) -> bool:
        text = " ".join(root.get_text(" ", strip=True) for root in roots)
        return len(text) >= self.minimum_chars

    def _sanitize(self, root: Tag) -> int:
        removed_nodes = 0
        for node in list(root.find_all(True)):
            if node.name not in ALLOWED_TAGS:
                node.unwrap()
                removed_nodes += 1
                continue
            attributes: dict[str, str] = {}
            if node.name == "a" and node.get("href"):
                href = str(node["href"]).strip()
                scheme = urlparse(href).scheme.lower()
                if scheme in {"", "http", "https"}:
                    attributes["href"] = href
                else:
                    removed_nodes += 1
            if node.name in {"td", "th"}:
                for key in ("colspan", "rowspan"):
                    if node.get(key):
                        attributes[key] = str(node[key])
            node.attrs.clear()
            for key, value in attributes.items():
                node[key] = value
        return removed_nodes

    def _plain_text(self, root: Tag) -> str:
        lines = (
            " ".join(line.split())
            for line in root.get_text("\n", strip=True).splitlines()
        )
        return "\n".join(line for line in lines if line)
