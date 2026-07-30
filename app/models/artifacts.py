from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class ArtifactDigest(BaseModel):
    name: str = Field(min_length=1)
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RawArtifactManifest(BaseModel):
    schema_version: str = "1.0"
    job_id: str = Field(min_length=1)
    item_id: str = Field(min_length=64, max_length=64)
    plugin: str = Field(min_length=1)
    source_url: HttpUrl
    state: str = "fetched"
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    page_type: str = "disease_detail"
    confidence: float = Field(ge=0, le=1)
    artifacts: dict[str, ArtifactDigest]
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
    snapshot_components: dict[str, str] = Field(default_factory=dict)
    baseline_job_id: str | None = None
    change_status: Literal["new", "updated", "unchanged"] | None = None
    changed_components: tuple[str, ...] = ()
    cleaner_version: str | None = None
    schema_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    parser_version: str | None = None
    prompt_version: str | None = None
    model_version: str | None = None
    warnings: tuple[str, ...] = ()


class RawFetchPolicy(BaseModel):
    max_attempts: int = Field(default=3, ge=1)
    base_delay_seconds: float = Field(default=2, ge=0)
    max_delay_seconds: float = Field(default=60, ge=0)
    capture_screenshot: bool = True


class RawFetchResult(BaseModel):
    job_id: str
    item_id: str
    artifact_dir: str
    manifest: RawArtifactManifest
    attempt_count: int = Field(ge=0)
    reused_artifacts: bool = False


class CleanArtifactResult(BaseModel):
    job_id: str
    item_id: str
    artifact_dir: str
    manifest: RawArtifactManifest
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    markdown_chars: int = Field(ge=1)
    warnings: tuple[str, ...] = ()
    reused_artifacts: bool = False
