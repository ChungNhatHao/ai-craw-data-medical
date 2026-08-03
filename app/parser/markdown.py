import hashlib
import re
import unicodedata
from collections.abc import Callable
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag
from bs4.element import NavigableString

BLANK_LINES = re.compile(r"\n{3,}")
INLINE_SPACE = re.compile(r"[ \t]+")


class MarkdownConverter:
    def __init__(self, canonicalize_url: Callable[[str], str]) -> None:
        self.canonicalize_url = canonicalize_url
        self.warnings: list[str] = []

    def convert(self, html: str, *, base_url: str) -> tuple[str, tuple[str, ...]]:
        self.warnings = []
        soup = BeautifulSoup(html, "lxml")
        root = soup.find("article") or soup.body or soup
        blocks = [
            rendered
            for child in root.children
            if (rendered := self._block(child, base_url=base_url, indent=0))
        ]
        markdown = normalize_markdown("\n\n".join(blocks))
        return markdown, tuple(dict.fromkeys(self.warnings))

    def _block(self, node: object, *, base_url: str, indent: int) -> str:
        if isinstance(node, NavigableString):
            return self._clean_inline(str(node))
        if not isinstance(node, Tag):
            return ""
        name = node.name.lower()
        if name in {f"h{level}" for level in range(1, 7)}:
            level = int(name[1])
            return f"{'#' * level} {self._inline_children(node, base_url)}".strip()
        if name == "p":
            return self._inline_children(node, base_url)
        if name in {"ul", "ol"}:
            return self._list(node, base_url=base_url, indent=indent)
        if name == "table":
            return self._table(node, base_url)
        if name == "blockquote":
            text = self._inline_children(node, base_url)
            return "\n".join(f"> {line}" for line in text.splitlines())
        if name == "pre":
            return f"```\n{node.get_text().strip()}\n```"
        if name == "br":
            return "\n"
        children = [
            rendered
            for child in node.children
            if (rendered := self._block(child, base_url=base_url, indent=indent))
        ]
        return "\n\n".join(children)

    def _inline_children(self, node: Tag, base_url: str) -> str:
        return self._clean_inline(
            "".join(self._inline(child, base_url) for child in node.children)
        )

    def _inline(self, node: object, base_url: str) -> str:
        if isinstance(node, NavigableString):
            return str(node)
        if not isinstance(node, Tag):
            return ""
        name = node.name.lower()
        text = "".join(self._inline(child, base_url) for child in node.children)
        if name in {"strong", "b"}:
            return f"**{self._clean_inline(text)}**"
        if name in {"em", "i"}:
            return f"*{self._clean_inline(text)}*"
        if name == "code":
            return f"`{text.strip()}`"
        if name == "br":
            return "\n"
        if name == "a":
            label = self._clean_inline(text)
            href = str(node.get("href") or "").strip()
            if not href:
                return label
            absolute = urljoin(base_url, href)
            if urlparse(absolute).scheme in {"http", "https"}:
                absolute = self.canonicalize_url(absolute)
            return f"[{label}]({absolute})"
        return text

    def _list(self, node: Tag, *, base_url: str, indent: int) -> str:
        lines: list[str] = []
        ordered = node.name.lower() == "ol"
        direct_items = node.find_all("li", recursive=False)
        for index, item in enumerate(direct_items, start=1):
            prefix = f"{index}. " if ordered else "- "
            inline_parts = [
                self._inline(child, base_url)
                for child in item.children
                if not (isinstance(child, Tag) and child.name in {"ul", "ol"})
            ]
            label = self._clean_inline("".join(inline_parts))
            lines.append(f"{'  ' * indent}{prefix}{label}")
            for nested in item.find_all(["ul", "ol"], recursive=False):
                nested_text = self._list(
                    nested,
                    base_url=base_url,
                    indent=indent + 1,
                )
                if nested_text:
                    lines.append(nested_text)
        return "\n".join(lines)

    def _table(self, node: Tag, base_url: str) -> str:
        rows: list[list[str]] = []
        header_flags: list[bool] = []
        for row in node.find_all("tr"):
            cells = row.find_all(["th", "td"], recursive=False)
            if not cells:
                continue
            rows.append(
                [
                    self._clean_inline(
                        self._inline_children(cell, base_url)
                    ).replace("|", "\\|").replace("\n", " / ")
                    for cell in cells
                ]
            )
            header_flags.append(all(cell.name == "th" for cell in cells))
        if not rows:
            fallback = self._clean_inline(node.get_text("\n", strip=True))
            self.warnings.append(
                "table_rendered_as_text" if fallback else "empty_table_omitted"
            )
            return fallback
        width = max(len(row) for row in rows)
        padded = [row + [""] * (width - len(row)) for row in rows]
        if not header_flags[0]:
            padded.insert(0, [f"Column {index}" for index in range(1, width + 1)])
        header = padded[0]
        body = padded[1:]
        lines = [
            f"| {' | '.join(header)} |",
            f"| {' | '.join('---' for _ in range(width))} |",
        ]
        lines.extend(f"| {' | '.join(row)} |" for row in body)
        return "\n".join(lines)

    def _clean_inline(self, value: str) -> str:
        lines = [
            INLINE_SPACE.sub(" ", line).strip()
            for line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        ]
        return "\n".join(line for line in lines if line).strip()


def normalize_markdown(markdown: str) -> str:
    normalized = unicodedata.normalize("NFC", markdown)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in normalized.split("\n")]
    return BLANK_LINES.sub("\n\n", "\n".join(lines)).strip() + "\n"


def content_hash(markdown: str) -> str:
    return hashlib.sha256(normalize_markdown(markdown).encode("utf-8")).hexdigest()
