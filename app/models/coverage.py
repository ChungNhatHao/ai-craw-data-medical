from pydantic import BaseModel, Field, HttpUrl


class DetectedTable(BaseModel):
    selector: str = Field(min_length=1)
    headers: tuple[str, ...] = ()
    row_count: int = Field(ge=0)


class PageStructureProfile(BaseModel):
    url: HttpUrl
    title: str | None = None
    content_root_candidates: tuple[str, ...] = ()
    heading_levels: tuple[int, ...] = ()
    tables: tuple[DetectedTable, ...] = ()
    tab_labels: tuple[str, ...] = ()
    form_count: int = Field(default=0, ge=0)
    same_origin_link_count: int = Field(default=0, ge=0)
    dynamic_markers: tuple[str, ...] = ()


class SiteProfile(BaseModel):
    schema_version: str = "1.0"
    plugin: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    representative_url: HttpUrl
    structure: PageStructureProfile
    required_tabs: tuple[str, ...] = ()
    captured_tabs: tuple[str, ...] = ()
    ready: bool
    blockers: tuple[str, ...] = ()


class ItemCoverageResult(BaseModel):
    schema_version: str = "1.0"
    item_id: str = Field(min_length=64, max_length=64)
    source_url: HttpUrl
    complete: bool
    checks: dict[str, bool] = Field(default_factory=dict)
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class JobCoverageReport(BaseModel):
    schema_version: str = "1.0"
    job_id: str = Field(min_length=1)
    complete: bool
    checked_items: int = Field(ge=0)
    complete_items: int = Field(ge=0)
    failed_items: int = Field(ge=0)
    results: tuple[ItemCoverageResult, ...] = ()
