from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator


class PageType(StrEnum):
    DISEASE_DETAIL = "disease_detail"
    DISEASE_LIST = "disease_list"
    HOME_OR_MENU = "home_or_menu"
    LOGIN = "login"
    BLOCKED_OR_CAPTCHA = "blocked_or_captcha"
    UNKNOWN = "unknown"


class PageClassification(BaseModel):
    page_type: PageType
    confidence: float = Field(ge=0, le=1)
    matched_signals: tuple[str, ...] = ()
    fingerprint: str = Field(min_length=12)


class NavigationCandidate(BaseModel):
    key: str = Field(min_length=1)
    action: Literal["goto", "click"]
    target: str = Field(min_length=1)
    label: str | None = None
    url: HttpUrl | None = None

    @model_validator(mode="after")
    def validate_target(self) -> "NavigationCandidate":
        if self.action == "goto" and self.url is None:
            raise ValueError("goto candidate requires a URL")
        return self


class NavigationPolicy(BaseModel):
    max_hops: int = Field(default=12, ge=1)
    max_same_fingerprint: int = Field(default=3, ge=2)
    max_no_progress: int = Field(default=2, ge=1)


class NavigationResult(BaseModel):
    classification: PageClassification
    hop_count: int
    visited_candidates: tuple[str, ...]

