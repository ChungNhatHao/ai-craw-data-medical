from bs4 import BeautifulSoup, Tag

from app.models.coverage import ItemCoverageResult
from app.models.discovery import DiscoveredItem
from app.models.disease import DiseaseDocument
from app.models.tabs import DiseaseTabContent, RawDiseaseTab
from app.parser.structured import TABLE_FIELD_MAP
from app.plugins.base import SitePlugin


class CoverageValidator:
    """Fail closed when source components cannot be accounted for in output."""

    def validate(
        self,
        *,
        plugin: SitePlugin,
        item: DiscoveredItem,
        raw_html: str,
        raw_tabs: tuple[RawDiseaseTab, ...],
        clean_tabs: tuple[DiseaseTabContent, ...],
        document: DiseaseDocument,
    ) -> ItemCoverageResult:
        blockers: list[str] = []
        checks: dict[str, bool] = {}

        checks["main_content_present"] = bool(raw_html.strip() and document.sections)
        if not checks["main_content_present"]:
            blockers.append("main_content_missing_from_output")

        checks["required_tabs_captured"] = plugin.raw_tabs_complete(raw_tabs)
        if not checks["required_tabs_captured"]:
            blockers.append("required_source_tabs_incomplete")

        clean_by_key = {tab.key: tab for tab in clean_tabs}
        document_by_key = {tab.key: tab for tab in document.tabs}
        tab_mapping_complete = True
        tables_complete = True
        hierarchy_complete = True
        related_complete = True
        for raw_tab in raw_tabs:
            clean = clean_by_key.get(raw_tab.key)
            output = document_by_key.get(raw_tab.key)
            if clean is None or output is None:
                tab_mapping_complete = False
                blockers.append(f"tab_not_mapped:{raw_tab.key}")
                continue
            if raw_tab.available and (
                not clean.available
                or not clean.plain_text.strip()
                or not output.available
            ):
                tab_mapping_complete = False
                blockers.append(f"tab_content_empty:{raw_tab.key}")
            source_tables = self._table_rows(raw_tab.html)
            clean_tables = tuple(
                self._canonical_rows(table.rows) for table in clean.tables
            )
            for source_rows in source_tables:
                if source_rows and source_rows not in clean_tables:
                    tables_complete = False
                    blockers.append(f"table_not_preserved:{raw_tab.key}")
                    break
            if (
                raw_tab.key in {"life_dd_tpd", "ip", "health"}
                and BeautifulSoup(raw_tab.html, "lxml").select_one(
                    "table#conditionTable"
                )
                is not None
                and (
                    clean.classification_table is None
                    or not clean.classification_table.rows
                )
            ):
                hierarchy_complete = False
                blockers.append(f"classification_hierarchy_missing:{raw_tab.key}")
            clean_details = {str(detail.url): detail for detail in clean.related_details}
            for raw_detail in raw_tab.related_details:
                clean_detail = clean_details.get(str(raw_detail.url))
                if raw_detail.available and (
                    clean_detail is None
                    or not clean_detail.available
                    or not clean_detail.plain_text.strip()
                ):
                    related_complete = False
                    blockers.append(f"related_detail_missing:{raw_tab.key}:{raw_detail.label}")

        checks["tabs_mapped_to_output"] = tab_mapping_complete
        checks["tables_preserved"] = tables_complete
        checks["classification_hierarchy_preserved"] = hierarchy_complete
        checks["related_details_preserved"] = related_complete
        missing_fields = tuple(
            warning.removeprefix("missing_field:")
            for warning in document.parse_metadata.warnings
            if warning.startswith("missing_field:")
        )
        source_fields = self._source_structured_fields(raw_tabs)
        source_field_misses = tuple(
            field for field in missing_fields if field in source_fields
        )
        absent_optional_fields = tuple(
            field for field in missing_fields if field not in source_fields
        )
        checks["structured_fields_complete"] = not source_field_misses
        blockers.extend(
            f"source_field_not_extracted:{field}"
            for field in source_field_misses
        )
        unique_blockers = tuple(dict.fromkeys(blockers))
        return ItemCoverageResult(
            item_id=item.item_id,
            source_url=item.canonical_url,
            complete=all(checks.values()) and not unique_blockers,
            checks=checks,
            blockers=unique_blockers,
            warnings=tuple(
                f"field_not_present_in_source:{field}"
                for field in absent_optional_fields
            ),
        )

    @classmethod
    def _table_rows(cls, html: str) -> tuple[tuple[tuple[str, ...], ...], ...]:
        soup = BeautifulSoup(html, "lxml")
        tables: list[tuple[tuple[str, ...], ...]] = []
        for table in soup.find_all("table"):
            if not isinstance(table, Tag):
                continue
            rows: list[tuple[str, ...]] = []
            for row in table.find_all("tr"):
                if str(row.get("aria-hidden", "")).casefold() == "true":
                    continue
                cells = row.find_all(["th", "td"], recursive=False)
                values = tuple(
                    cls._canonical_cell(cell.get_text(" ", strip=True))
                    for cell in cells
                )
                if values and any(values):
                    rows.append(values)
            if rows:
                tables.append(tuple(rows))
        return tuple(tables)

    @classmethod
    def _canonical_rows(
        cls,
        rows: tuple[tuple[str, ...], ...],
    ) -> tuple[tuple[str, ...], ...]:
        return tuple(
            values
            for row in rows
            if any(values := tuple(cls._canonical_cell(cell) for cell in row))
        )

    @staticmethod
    def _canonical_cell(value: str) -> str:
        # DOM formatting may insert spaces around inline tags (e.g. m<sup>2</sup>)
        # without changing the source value. Coverage compares characters, not layout.
        return "".join(value.casefold().split())

    @staticmethod
    def _source_structured_fields(
        raw_tabs: tuple[RawDiseaseTab, ...],
    ) -> frozenset[str]:
        info = next((tab for tab in raw_tabs if tab.key == "info"), None)
        if info is None or not info.html.strip():
            return frozenset()
        soup = BeautifulSoup(info.html, "lxml")
        labels: set[str] = set()
        for row in soup.find_all("tr"):
            first = row.find(["th", "td"], recursive=False)
            if isinstance(first, Tag):
                labels.add(" ".join(first.get_text(" ", strip=True).casefold().split()))
        for heading in soup.find_all([f"h{level}" for level in range(1, 7)]):
            if isinstance(heading, Tag):
                labels.add(" ".join(heading.get_text(" ", strip=True).casefold().split()))
        return frozenset(
            field
            for label in labels
            if (field := TABLE_FIELD_MAP.get(label)) is not None
        )
