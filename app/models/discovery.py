from pydantic import BaseModel, Field, HttpUrl

from app.models.navigation import PageType


class DiscoveredItem(BaseModel):
    item_id: str = Field(min_length=64, max_length=64)
    source_url: HttpUrl
    canonical_url: HttpUrl
    title_hint: str | None = None
    discovery_page: HttpUrl


class DiscoveryPolicy(BaseModel):
    max_items: int = Field(default=1_000, ge=1)
    max_pages: int = Field(default=100, ge=1)
    max_no_new_rounds: int = Field(default=2, ge=1)


class DiscoveryResult(BaseModel):
    items: tuple[DiscoveredItem, ...]
    pages_visited: int
    stopped_reason: str
    limits_reached: tuple[str, ...] = ()


class DiscoveryCandidate(BaseModel):
    url: HttpUrl
    label: str | None = None
    score: int = Field(ge=0, le=100)
    source_url: HttpUrl


class DiscoveryEvaluation(BaseModel):
    url: HttpUrl
    label: str | None = None
    page_type: PageType
    confidence: float = Field(ge=0, le=1)
    signals: tuple[str, ...] = ()
    accepted: bool


class IntelligentDiscoveryResult(BaseModel):
    items: tuple[DiscoveredItem, ...]
    pages_evaluated: int
    candidates_seen: int
    stopped_reason: str
    evaluations: tuple[DiscoveryEvaluation, ...]
