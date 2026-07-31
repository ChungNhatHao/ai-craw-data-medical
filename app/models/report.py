from datetime import UTC, datetime

from pydantic import BaseModel, Field, HttpUrl

from app.models.category import CategoryItemProvenance
from app.models.crawl import CrawlJob, JobStatus


class ReportItem(BaseModel):
    item_id: str = Field(min_length=64, max_length=64)
    title: str | None = None
    source_url: HttpUrl
    canonical_url: HttpUrl
    status: str = Field(min_length=1)
    artifact_dir: str | None = None
    artifacts: tuple[str, ...] = ()
    complete_artifact_set: bool = False
    content_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    snapshot_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    previous_snapshot_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    baseline_job_id: str | None = None
    change_status: str | None = None
    changed_components: tuple[str, ...] = ()
    checked_at: str | None = None
    last_error_code: str | None = None
    warnings: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()
    data_complete: bool = False
    provenance: tuple[CategoryItemProvenance, ...] = ()


class JobReport(BaseModel):
    schema_version: str = "1.1"
    job_id: str = Field(min_length=1)
    plugin: str = Field(min_length=1)
    status: JobStatus
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    counts: dict[str, int]
    total_items: int = Field(ge=0)
    successful_items: int = Field(ge=0)
    failed_items: int = Field(ge=0)
    new_items: int = Field(default=0, ge=0)
    updated_items: int = Field(default=0, ge=0)
    unchanged_items: int = Field(default=0, ge=0)
    items_with_missing_fields: int = Field(default=0, ge=0)
    missing_field_count: int = Field(default=0, ge=0)
    items: tuple[ReportItem, ...]
    warnings: tuple[str, ...] = ()


class ReportDigest(BaseModel):
    name: str = Field(min_length=1)
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class FinalJobManifest(BaseModel):
    schema_version: str = "1.0"
    job_id: str = Field(min_length=1)
    plugin: str = Field(min_length=1)
    status: JobStatus
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    report: ReportDigest
    item_count: int = Field(ge=0)
    successful_items: int = Field(ge=0)
    failed_items: int = Field(ge=0)


class JobStatusResponse(BaseModel):
    job: CrawlJob
    counts: dict[str, int]
    report_available: bool
