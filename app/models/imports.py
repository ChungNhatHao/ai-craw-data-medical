from typing import Literal

from pydantic import BaseModel, Field


class ImportSearchAttempt(BaseModel):
    disease_name: str = Field(min_length=1)
    query: str = Field(min_length=1)
    method: str = "site_search_form:#searchTerm"
    search_url: str | None = None
    inspected_links: int = Field(default=0, ge=0)
    exact_matches: int = Field(default=0, ge=0)
    autocomplete_suggestions: tuple[str, ...] = ()
    autocomplete_selected_name: str | None = None
    autocomplete_selected_names: tuple[str, ...] = ()
    autocomplete_resolved_names: tuple[str, ...] = ()
    autocomplete_decision_source: Literal[
        "gemini",
        "deterministic_fallback",
        "all_suggestions",
        "none",
    ] = "none"
    autocomplete_confidence: float | None = Field(default=None, ge=0, le=1)
    autocomplete_reason_code: str | None = None
    autocomplete_reason: str | None = None
    match_strategy: str | None = None
    search_reason_code: str | None = None
    selected_url: str | None = None
    selected_urls: tuple[str, ...] = ()
    confirmed_disease_count: int = Field(default=0, ge=0)
    skipped_existing_count: int = Field(default=0, ge=0)
    skipped_existing_urls: tuple[str, ...] = ()
    status: Literal["matched", "not_found"]
    reason_code: str
    reason: str
    steps: tuple[str, ...]


class ImportSearchAudit(BaseModel):
    schema_version: str = "1.0"
    job_id: str
    requested_count: int = Field(ge=0)
    matched_count: int = Field(ge=0)
    not_found_count: int = Field(ge=0)
    category_expansion_enabled: bool = False
    confirmed_disease_count: int = Field(default=0, ge=0)
    attempts: tuple[ImportSearchAttempt, ...]
