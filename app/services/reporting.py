from app.models.report import JobReport, ReportItem
from app.repositories.category_provenance import CategoryProvenanceRepository
from app.repositories.items import ItemRepository
from app.repositories.jobs import JobRepository
from app.storage.artifacts import ArtifactStore

REQUIRED_MVP_ARTIFACTS = frozenset(
    {
        "raw_html",
        "screenshot",
        "content_html",
        "markdown",
        "disease_json",
    }
)
REQUIRED_TAB_ARTIFACTS = frozenset({"tabs_raw", "tabs"})
FAILED_STATUSES = frozenset({"retryable_failed", "failed"})
MISSING_FIELD_PREFIX = "missing_field:"


class ReportingService:
    def __init__(
        self,
        *,
        jobs: JobRepository,
        items: ItemRepository,
        artifacts: ArtifactStore,
        provenance: CategoryProvenanceRepository | None = None,
    ) -> None:
        self.jobs = jobs
        self.items = items
        self.artifacts = artifacts
        self.provenance = provenance or CategoryProvenanceRepository(
            items.database
        )

    async def generate(self, job_id: str) -> JobReport:
        job = await self.jobs.get(job_id)
        if job is None:
            raise KeyError(f"Unknown job: {job_id}")
        discovered = await self.items.list_for_job(job_id)
        required_artifacts = (
            REQUIRED_MVP_ARTIFACTS | REQUIRED_TAB_ARTIFACTS
            if job.plugin == "genre_manuals"
            else REQUIRED_MVP_ARTIFACTS
        )
        provenance_by_item = await self.provenance.list_for_job(job_id)
        coverage = self.artifacts.read_job_json(
            job_id,
            "coverage-report.json",
        )
        raw_coverage_results = coverage.get("results") if coverage else None
        coverage_blockers_by_item: dict[str, tuple[str, ...]] = {}
        if isinstance(raw_coverage_results, list):
            for result in raw_coverage_results:
                if not isinstance(result, dict):
                    continue
                item_id = result.get("item_id")
                blockers = result.get("blockers")
                if not isinstance(item_id, str) or not isinstance(blockers, list):
                    continue
                coverage_blockers_by_item[item_id] = tuple(
                    str(value) for value in blockers
                )
        report_items: list[ReportItem] = []
        for item in discovered:
            checkpoint = await self.items.get_checkpoint(job_id, item.item_id)
            if checkpoint is None:
                continue
            manifest = self.artifacts.load_item_manifest(job_id, item)
            artifact_names = (
                tuple(sorted(manifest.artifacts))
                if manifest is not None
                else ()
            )
            manifest_warnings = (
                manifest.warnings if manifest is not None else ()
            )
            disease_document = self.artifacts.read_disease_document(
                job_id,
                item,
            )
            coverage_blockers = coverage_blockers_by_item.get(item.item_id)
            missing_fields = (
                tuple(
                    dict.fromkeys(
                        blocker.removeprefix("source_field_not_extracted:")
                        for blocker in coverage_blockers
                        if blocker.startswith("source_field_not_extracted:")
                    )
                )
                if coverage_blockers is not None
                else tuple(
                    dict.fromkeys(
                        warning.removeprefix(MISSING_FIELD_PREFIX)
                        for warning in manifest_warnings
                        if warning.startswith(MISSING_FIELD_PREFIX)
                        and warning.removeprefix(MISSING_FIELD_PREFIX)
                    )
                )
            )
            report_items.append(
                ReportItem(
                    item_id=item.item_id,
                    title=item.title_hint,
                    source_url=item.source_url,
                    canonical_url=item.canonical_url,
                    status=checkpoint.status,
                    artifact_dir=checkpoint.artifact_dir,
                    artifacts=artifact_names,
                    complete_artifact_set=(
                        checkpoint.status == "parsed"
                        and required_artifacts.issubset(artifact_names)
                    ),
                    content_hash=checkpoint.content_hash,
                    snapshot_hash=checkpoint.snapshot_hash,
                    previous_snapshot_hash=checkpoint.previous_snapshot_hash,
                    baseline_job_id=checkpoint.baseline_job_id,
                    change_status=checkpoint.change_status,
                    changed_components=checkpoint.changed_components,
                    checked_at=checkpoint.checked_at,
                    last_error_code=checkpoint.last_error_code,
                    warnings=manifest_warnings,
                    missing_fields=missing_fields,
                    data_complete=(
                        checkpoint.status == "parsed"
                        and not missing_fields
                    ),
                    menu_hierarchy=(
                        disease_document.menu_hierarchy
                        if disease_document is not None
                        else ()
                    ),
                    provenance=provenance_by_item.get(item.item_id, ()),
                )
            )

        counts = await self.items.count_by_status(job_id)
        failed = sum(
            count for status, count in counts.items() if status in FAILED_STATUSES
        )
        category_expansion = self.artifacts.read_job_json(
            job_id,
            "category-expansion.json",
        )
        raw_category_warnings = (
            category_expansion.get("limits_reached", [])
            if category_expansion is not None
            else []
        )
        category_warnings = (
            tuple(
                str(value)
                for value in raw_category_warnings
            )
            if isinstance(raw_category_warnings, list)
            else ()
        )
        coverage_complete = bool(
            coverage is not None and coverage.get("complete") is True
        )
        raw_coverage_failed = (
            coverage.get("failed_items", 0) if coverage is not None else 0
        )
        coverage_failed_items = (
            int(raw_coverage_failed)
            if isinstance(raw_coverage_failed, int)
            else 0
        )
        report = JobReport(
            job_id=job_id,
            plugin=job.plugin,
            status=job.status,
            counts=counts,
            total_items=len(report_items),
            successful_items=counts.get("parsed", 0),
            failed_items=failed,
            new_items=sum(
                item.change_status == "new" for item in report_items
            ),
            updated_items=sum(
                item.change_status == "updated" for item in report_items
            ),
            unchanged_items=sum(
                item.change_status == "unchanged" for item in report_items
            ),
            items_with_missing_fields=sum(
                bool(item.missing_fields) for item in report_items
            ),
            missing_field_count=sum(
                len(item.missing_fields) for item in report_items
            ),
            coverage_complete=coverage_complete,
            coverage_failed_items=coverage_failed_items,
            items=tuple(report_items),
            warnings=tuple(
                dict.fromkeys(
                    (
                        *category_warnings,
                        *(() if coverage_complete else ("coverage_incomplete",)),
                    )
                )
            ),
        )
        self.artifacts.persist_job_report(report)
        return report
