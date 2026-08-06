import re

from bs4 import BeautifulSoup

from app.core.errors import CrawlerError, ErrorCode
from app.models.artifacts import CleanArtifactResult
from app.models.discovery import DiscoveredItem
from app.models.tabs import (
    DiseaseTabContent,
    DiseaseTabTable,
    RawDiseaseTab,
    RawTabRelatedDetail,
    TabRelatedDetail,
)
from app.parser.classification import extract_classification_table
from app.parser.extractor import ContentExtractor
from app.parser.markdown import MarkdownConverter, content_hash
from app.plugins.base import SitePlugin
from app.repositories.attempts import AttemptRepository
from app.repositories.items import ItemRepository
from app.services.incremental import (
    changed_components,
    snapshot_components,
    snapshot_hash,
)
from app.storage.artifacts import ArtifactStore

CLEANER_VERSION = "1.4.0"
ICD_CODE_PATTERN = re.compile(r"^[A-Z]\d[\dA-Z.]*$")


class CleaningService:
    def __init__(
        self,
        *,
        plugin: SitePlugin,
        items: ItemRepository,
        attempts: AttemptRepository,
        artifacts: ArtifactStore,
        extractor: ContentExtractor,
    ) -> None:
        self.plugin = plugin
        self.items = items
        self.attempts = attempts
        self.artifacts = artifacts
        self.extractor = extractor

    async def run(
        self,
        *,
        job_id: str,
        item: DiscoveredItem,
    ) -> CleanArtifactResult:
        recovered = self.artifacts.load_valid_clean(
            job_id,
            item,
            cleaner_version=CLEANER_VERSION,
        )
        if recovered is not None:
            manifest, artifact_dir = recovered
            if manifest.content_hash is None:
                raise CrawlerError(
                    ErrorCode.CONTENT_INVALID,
                    "Clean manifest is missing its content hash",
                )
            await self.items.mark_cleaned(
                job_id,
                item.item_id,
                manifest.content_hash,
                artifact_dir,
            )
            if manifest.snapshot_hash and manifest.change_status:
                await self.items.record_incremental(
                    job_id=job_id,
                    item_id=item.item_id,
                    snapshot_hash=manifest.snapshot_hash,
                    previous_snapshot_hash=manifest.previous_snapshot_hash,
                    baseline_job_id=manifest.baseline_job_id,
                    change_status=manifest.change_status,
                    changed_components=manifest.changed_components,
                )
            markdown = self._read_markdown(job_id, item)
            return CleanArtifactResult(
                job_id=job_id,
                item_id=item.item_id,
                artifact_dir=artifact_dir,
                manifest=manifest,
                content_hash=manifest.content_hash,
                markdown_chars=len(markdown),
                warnings=manifest.warnings,
                reused_artifacts=True,
            )

        attempt_no = await self.attempts.next_attempt_no(
            job_id,
            item.item_id,
            "clean_markdown",
        )
        attempt_id = await self.attempts.start(
            job_id,
            item.item_id,
            attempt_no,
            "clean_markdown",
        )
        await self.items.mark_cleaning(job_id, item.item_id)
        try:
            raw_html = self.artifacts.read_raw_html(job_id, item)
            extracted = self.extractor.extract(
                raw_html,
                root_selectors=self.plugin.content_root_selectors(),
                title_selectors=self.plugin.content_title_selectors(),
            )
            markdown, markdown_warnings = MarkdownConverter(
                self.plugin.canonicalize_url
            ).convert(
                extracted.html,
                base_url=str(item.canonical_url),
            )
            if len(markdown.strip()) < self.extractor.minimum_chars:
                raise CrawlerError(
                    ErrorCode.CONTENT_EMPTY,
                    "Markdown content is empty or below minimum length",
                )
            digest = content_hash(markdown)
            warnings = tuple(
                dict.fromkeys((*extracted.warnings, *markdown_warnings))
            )
            tabs = self._clean_tabs(
                self.artifacts.read_raw_tabs(job_id, item),
                base_url=str(item.canonical_url),
            )
            components = snapshot_components(digest, tabs)
            composite_hash = snapshot_hash(components)
            baseline = await self.items.find_incremental_baseline(
                job_id=job_id,
                item_id=item.item_id,
                plugin=self.plugin.name,
            )
            previous_components: dict[str, str] = {}
            if baseline is None:
                change_status = "new"
                component_changes = tuple(sorted(components))
            else:
                baseline_manifest = self.artifacts.load_item_manifest(
                    baseline.job_id,
                    baseline.item,
                )
                if baseline_manifest is not None:
                    previous_components = baseline_manifest.snapshot_components
                change_status = (
                    "unchanged"
                    if baseline.snapshot_hash == composite_hash
                    else "updated"
                )
                component_changes = changed_components(
                    components,
                    previous_components,
                )
            incremental_warning = {
                "new": "incremental_new_content",
                "updated": "incremental_content_updated",
                "unchanged": "incremental_already_crawled_no_change",
            }[change_status]
            warnings = tuple(dict.fromkeys((*warnings, incremental_warning)))
            manifest, artifact_dir = self.artifacts.persist_clean(
                job_id=job_id,
                item=item,
                content_html=extracted.html,
                markdown=markdown,
                content_hash=digest,
                cleaner_version=CLEANER_VERSION,
                warnings=warnings,
                snapshot_hash=composite_hash,
                snapshot_components=components,
                previous_snapshot_hash=(
                    baseline.snapshot_hash if baseline is not None else None
                ),
                baseline_job_id=(
                    baseline.job_id if baseline is not None else None
                ),
                change_status=change_status,
                changed_components=component_changes,
                tabs=tabs,
            )
            await self.items.mark_cleaned(
                job_id,
                item.item_id,
                digest,
                artifact_dir,
            )
            await self.items.record_incremental(
                job_id=job_id,
                item_id=item.item_id,
                snapshot_hash=composite_hash,
                previous_snapshot_hash=(
                    baseline.snapshot_hash if baseline is not None else None
                ),
                baseline_job_id=(
                    baseline.job_id if baseline is not None else None
                ),
                change_status=change_status,
                changed_components=component_changes,
            )
        except CrawlerError as exc:
            await self.attempts.finish(
                attempt_id,
                result="failure",
                error_code=exc.code.value,
                error_message=str(exc),
            )
            await self.items.mark_clean_failed(
                job_id,
                item.item_id,
                exc.code.value,
            )
            raise
        except Exception as exc:
            unexpected = CrawlerError(
                ErrorCode.UNEXPECTED,
                "Unexpected failure while cleaning disease content",
            )
            await self.attempts.finish(
                attempt_id,
                result="failure",
                error_code=unexpected.code.value,
                error_message=str(unexpected),
            )
            await self.items.mark_clean_failed(
                job_id,
                item.item_id,
                unexpected.code.value,
            )
            raise unexpected from exc
        else:
            await self.attempts.finish(attempt_id, result="success")
            return CleanArtifactResult(
                job_id=job_id,
                item_id=item.item_id,
                artifact_dir=artifact_dir,
                manifest=manifest,
                content_hash=digest,
                markdown_chars=len(markdown),
                warnings=warnings,
            )

    def _read_markdown(self, job_id: str, item: DiscoveredItem) -> str:
        directory, _ = self.artifacts.item_directory(job_id, item)
        try:
            return (directory / "markdown.md").read_text(encoding="utf-8")
        except OSError as exc:
            raise CrawlerError(
                ErrorCode.CONTENT_INVALID,
                "Markdown artifact could not be read",
            ) from exc

    def _clean_tabs(
        self,
        raw_tabs: tuple[RawDiseaseTab, ...],
        *,
        base_url: str,
    ) -> tuple[DiseaseTabContent, ...]:
        cleaned: list[DiseaseTabContent] = []
        tab_extractor = ContentExtractor(minimum_chars=1)
        for tab in raw_tabs:
            if not tab.available or not tab.html.strip():
                cleaned.append(
                    DiseaseTabContent(
                        key=tab.key,
                        label=tab.label,
                        source_url=tab.source_url,
                        available=False,
                        warnings=((tab.warning or "tab_content_unavailable"),),
                    )
                )
                continue
            try:
                extracted = tab_extractor.extract(
                    tab.html,
                    root_selectors=("article", ".tabContainer", "body"),
                    title_selectors=(),
                )
                markdown, markdown_warnings = MarkdownConverter(
                    self.plugin.canonicalize_url
                ).convert(
                    extracted.html,
                    base_url=base_url,
                )
            except CrawlerError:
                cleaned.append(
                    DiseaseTabContent(
                        key=tab.key,
                        label=tab.label,
                        source_url=tab.source_url,
                        available=False,
                        warnings=("tab_clean_failed",),
                    )
                )
                continue
            tables = self._extract_tables(extracted.html)
            if tab.key == "info":
                summary_table = self._extract_info_summary_table(tab.html)
                if summary_table is not None:
                    tables = (summary_table, *tables)
            related_details = self._clean_related_details(tab.related_details)
            cleaned.append(
                DiseaseTabContent(
                    key=tab.key,
                    label=tab.label,
                    source_url=tab.source_url,
                    plain_text=extracted.plain_text,
                    markdown=markdown,
                    tables=tables,
                    classification_table=extract_classification_table(
                        tab.html,
                        related_details=related_details,
                    ),
                    content_hash=content_hash(markdown),
                    warnings=tuple(
                        dict.fromkeys(
                            (*extracted.warnings, *markdown_warnings)
                        )
                    ),
                    related_details=related_details,
                )
            )
        return tuple(cleaned)

    def _clean_related_details(
        self,
        raw_details: tuple[RawTabRelatedDetail, ...],
    ) -> tuple[TabRelatedDetail, ...]:
        cleaned: list[TabRelatedDetail] = []
        extractor = ContentExtractor(minimum_chars=1)
        for detail in raw_details:
            if not detail.available or not detail.html.strip():
                cleaned.append(
                    TabRelatedDetail(
                        label=detail.label,
                        url=detail.url,
                        available=False,
                        warnings=(
                            detail.warning or "related_content_unavailable",
                        ),
                    )
                )
                continue
            try:
                extracted = extractor.extract(
                    detail.html,
                    root_selectors=(".genrearticle", "article", "main", "#content"),
                    title_selectors=("h2.pageTitle", "h1", "#content h2"),
                )
                markdown, warnings = MarkdownConverter(
                    self.plugin.canonicalize_url
                ).convert(
                    extracted.html,
                    base_url=str(detail.url),
                )
            except CrawlerError:
                cleaned.append(
                    TabRelatedDetail(
                        label=detail.label,
                        url=detail.url,
                        available=False,
                        warnings=("related_clean_failed",),
                    )
                )
                continue
            cleaned.append(
                TabRelatedDetail(
                    label=detail.label,
                    url=detail.url,
                    plain_text=extracted.plain_text,
                    markdown=markdown,
                    content_hash=content_hash(markdown),
                    warnings=tuple(
                        dict.fromkeys((*extracted.warnings, *warnings))
                    ),
                )
            )
        return tuple(cleaned)

    def _extract_tables(self, html: str) -> tuple[DiseaseTabTable, ...]:
        soup = BeautifulSoup(html, "lxml")
        tables: list[DiseaseTabTable] = []
        for table in soup.find_all("table"):
            rows: list[tuple[str, ...]] = []
            for row in table.find_all("tr"):
                cells = row.find_all(["th", "td"], recursive=False)
                values = tuple(
                    " ".join(cell.get_text(" ", strip=True).split())
                    for cell in cells
                )
                if values and any(values):
                    rows.append(values)
            if rows:
                tables.append(DiseaseTabTable(rows=tuple(rows)))
        return tuple(tables)

    def _extract_info_summary_table(
        self,
        html: str,
    ) -> DiseaseTabTable | None:
        """Create chunk-friendly rows for the non-table Info preamble."""
        soup = BeautifulSoup(html, "lxml")
        rows: list[tuple[str, ...]] = []
        synonym_blocks = [
            " ".join(node.get_text(" ", strip=True).split())
            for node in soup.select(".synonyms")
            if node.get_text(" ", strip=True)
        ]
        codes: list[str] = []
        aliases: list[str] = []
        for block in synonym_blocks:
            parts = tuple(part.strip() for part in block.split("*") if part.strip())
            if parts and all(ICD_CODE_PATTERN.fullmatch(part) for part in parts):
                codes.append(block)
            else:
                aliases.append(block)
        if codes:
            rows.append(("Codes", " * ".join(codes)))
        if aliases:
            rows.append(("Aliases", " * ".join(aliases)))

        summary_blocks: list[str] = []
        for intro in soup.select(".intro"):
            for child in intro.children:
                if getattr(child, "name", None) == "table":
                    break
                if getattr(child, "name", None) != "p":
                    continue
                text = " ".join(child.get_text(" ", strip=True).split())
                if text:
                    summary_blocks.append(text)
            if summary_blocks:
                break
        if summary_blocks:
            rows.append(("Summary", "\n\n".join(summary_blocks)))
        return DiseaseTabTable(rows=tuple(rows)) if rows else None
