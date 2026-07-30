from typing import NotRequired, TypedDict


class CrawlState(TypedDict):
    job_id: str
    plugin_name: str
    status: str
    discovered_count: int
    error: NotRequired[str | None]
    current_page_type: NotRequired[str | None]
    navigation_hop_count: NotRequired[int]
    no_progress_count: NotRequired[int]
    visited_page_fingerprints: NotRequired[list[str]]


class RawFetchState(TypedDict):
    job_id: str
    item_id: str
    stage: str
    artifact_dir: NotRequired[str | None]
    attempt_count: NotRequired[int]
    reused_artifacts: NotRequired[bool]
