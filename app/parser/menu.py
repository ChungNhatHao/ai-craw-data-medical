from collections.abc import Callable
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from app.models.disease import MenuHierarchyLevel

BREADCRUMB_SELECTORS = (
    "ul.breadcrumb",
    "ol.breadcrumb",
    "nav[aria-label*='breadcrumb' i]",
    ".breadcrumbs",
)


def extract_menu_hierarchy(
    html: str,
    *,
    page_url: str,
    current_label: str | None,
    canonicalize_url: Callable[[str], str],
) -> tuple[MenuHierarchyLevel, ...]:
    """Extract the authoritative Home-to-current-page breadcrumb."""
    soup = BeautifulSoup(html, "lxml")
    container = next(
        (
            candidate
            for selector in BREADCRUMB_SELECTORS
            if (candidate := soup.select_one(selector)) is not None
        ),
        None,
    )
    if container is None:
        return ()
    items = container.find_all("li", recursive=False)
    values: list[tuple[str, str | None]] = []
    for item in items:
        label = " ".join(item.get_text(" ", strip=True).split())
        if not label:
            continue
        link = item.find("a", href=True)
        values.append(
            (
                label,
                _resolve_url(
                    str(link.get("href")),
                    page_url=page_url,
                    canonicalize_url=canonicalize_url,
                )
                if isinstance(link, Tag)
                else None,
            )
        )
    normalized_current = " ".join((current_label or "").casefold().split())
    if normalized_current and (
        not values
        or " ".join(values[-1][0].casefold().split()) != normalized_current
    ):
        values.append((str(current_label).strip(), page_url))
    if not values:
        return ()
    last = len(values) - 1
    output: list[MenuHierarchyLevel] = []
    for level, (label, url) in enumerate(values):
        is_current = level == last
        output.append(
            MenuHierarchyLevel(
                level=level,
                distance_from_disease=last - level,
                label=label,
                url=(
                    canonicalize_url(page_url)
                    if is_current
                    else url
                ),
                is_current=is_current,
            )
        )
    return tuple(output)


def _resolve_url(
    value: str,
    *,
    page_url: str,
    canonicalize_url: Callable[[str], str],
) -> str | None:
    absolute = urljoin(page_url, value.strip())
    if urlparse(absolute).scheme not in {"http", "https"}:
        return None
    return canonicalize_url(absolute)
