import hashlib
import re
from typing import Any

from bs4 import BeautifulSoup, Tag

from app.models.tabs import (
    ClassificationNode,
    ClassificationRow,
    DiseaseClassificationTable,
)

PADDING_LEFT = re.compile(
    r"(?:^|;)\s*padding-left\s*:\s*([\d.]+)px",
    re.IGNORECASE,
)
LEVEL_WIDTH_PX = 25


def extract_classification_table(
    html: str,
) -> DiseaseClassificationTable | None:
    soup = BeautifulSoup(html, "lxml")
    data_table = soup.select_one("table#conditionTable")
    if not isinstance(data_table, Tag):
        return None
    warnings: list[str] = []
    headers = _extract_headers(soup, data_table)
    if not headers:
        warnings.append("classification_header_missing")
    rows: list[ClassificationRow] = []
    path_stack: list[str] = []
    seen_paths: set[tuple[str, ...]] = set()
    for row in data_table.find_all("tr"):
        if str(row.get("aria-hidden", "")).casefold() == "true":
            continue
        cells = row.find_all(["th", "td"], recursive=False)
        if not cells:
            continue
        raw_cells = tuple(_cell_text(cell) for cell in cells)
        if not raw_cells or not raw_cells[0]:
            continue
        level = _classification_level(cells[0], warnings)
        if level > len(path_stack):
            warnings.append("classification_level_jump")
            level = len(path_stack)
        path_stack = path_stack[:level]
        classification = raw_cells[0]
        path_stack.append(classification)
        classification_path = tuple(path_stack)
        if classification_path in seen_paths:
            warnings.append("classification_duplicate_path")
        seen_paths.add(classification_path)
        aligned = _align_cells(raw_cells, headers, warnings)
        ratings, code = _ratings_and_code(headers, aligned)
        rows.append(
            ClassificationRow(
                classification_id=_classification_id(
                    classification_path
                ),
                parent_classification_id=(
                    _classification_id(classification_path[:-1])
                    if level > 0
                    else None
                ),
                parent_classification=(
                    classification_path[-2] if level > 0 else None
                ),
                classification=classification,
                level=level,
                classification_path=classification_path,
                is_group=not any(ratings.values()) and not code,
                ratings=ratings,
                code=code,
                raw_cells=aligned,
            )
        )
    return DiseaseClassificationTable(
        headers=headers,
        rows=tuple(rows),
        tree=_build_tree(rows),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _extract_headers(
    soup: BeautifulSoup,
    data_table: Tag,
) -> tuple[str, ...]:
    floating = soup.select_one("table.floatThead-table")
    candidates = (floating, data_table)
    for table in candidates:
        if not isinstance(table, Tag):
            continue
        for row in table.find_all("tr"):
            cells = row.find_all(["th", "td"], recursive=False)
            if not cells:
                continue
            values = _trim_trailing_empty(
                tuple(
                    _cell_text(cell)
                    or str(cell.get("aria-label") or "").strip()
                    for cell in cells
                )
            )
            if values and values[0].casefold() == "classification":
                return values
    return ()


def _classification_level(
    cell: Tag,
    warnings: list[str],
) -> int:
    raw_classes = cell.get("class")
    classes = (
        {str(value).casefold() for value in raw_classes}
        if isinstance(raw_classes, list)
        else set()
    )
    if "level-0" in classes:
        return 0
    style = str(cell.get("style") or "")
    match = PADDING_LEFT.search(style)
    if match is None:
        warnings.append("classification_level_missing")
        return 0
    padding = float(match.group(1))
    quotient = padding / LEVEL_WIDTH_PX
    level = round(quotient)
    if abs(quotient - level) > 0.01:
        warnings.append("classification_level_invalid")
    return max(level, 0)


def _align_cells(
    cells: tuple[str, ...],
    headers: tuple[str, ...],
    warnings: list[str],
) -> tuple[str, ...]:
    if not headers:
        return _trim_trailing_empty(cells)
    if len(cells) > len(headers) and not any(cells[len(headers) :]):
        return cells[: len(headers)]
    if len(cells) != len(headers):
        warnings.append("classification_columns_mismatch")
    if len(cells) < len(headers):
        return (*cells, *("" for _ in range(len(headers) - len(cells))))
    return cells[: len(headers)]


def _ratings_and_code(
    headers: tuple[str, ...],
    cells: tuple[str, ...],
) -> tuple[dict[str, str], str | None]:
    ratings: dict[str, str] = {}
    code: str | None = None
    for header, value in zip(headers[1:], cells[1:], strict=False):
        if header.casefold() == "code":
            code = value or None
        elif header:
            ratings[header] = value
    return ratings, code


def _classification_id(path: tuple[str, ...]) -> str:
    identity = "\x1f".join(" ".join(value.casefold().split()) for value in path)
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _build_tree(
    rows: list[ClassificationRow],
) -> tuple[ClassificationNode, ...]:
    roots: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = []
    for row in rows:
        node: dict[str, Any] = {
            "classification_id": row.classification_id,
            "parent_classification_id": row.parent_classification_id,
            "parent_classification": row.parent_classification,
            "classification": row.classification,
            "level": row.level,
            "classification_path": row.classification_path,
            "is_group": row.is_group,
            "ratings": row.ratings,
            "code": row.code,
            "children": [],
        }
        stack = stack[: row.level]
        if row.level == 0:
            roots.append(node)
        else:
            stack[row.level - 1]["children"].append(node)
        stack.append(node)
    return tuple(ClassificationNode.model_validate(value) for value in roots)


def _cell_text(cell: Tag) -> str:
    return " ".join(cell.get_text(" ", strip=True).split())


def _trim_trailing_empty(values: tuple[str, ...]) -> tuple[str, ...]:
    end = len(values)
    while end and not values[end - 1]:
        end -= 1
    return values[:end]
