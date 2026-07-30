from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, SecretStr, model_validator


class RunStageName(StrEnum):
    VALIDATE = "validate"
    AUTHENTICATE = "authenticate"
    NAVIGATE = "navigate"
    DISCOVER = "discover"
    FETCH = "fetch"
    CLEAN = "clean"
    PARSE = "parse"
    REPORT = "report"


class RunState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"


class StageState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class RunRequest(BaseModel):
    url: HttpUrl
    username: SecretStr
    password: SecretStr
    max_items: int = Field(default=10, ge=1, le=25)
    discovery_mode: Literal["automatic", "import"] = "automatic"
    disease_names: tuple[str, ...] = ()
    authorization_confirmed: bool
    agentic_discovery: bool = False
    ai_normalization: bool = False
    expand_disease_categories: bool = True
    category_max_depth: int = Field(default=5, ge=1, le=8)
    category_max_nodes: int = Field(default=100, ge=1, le=250)
    category_max_diseases: int = Field(default=100, ge=1, le=250)

    @model_validator(mode="after")
    def normalize_imported_disease_names(self) -> "RunRequest":
        names: list[str] = []
        seen: set[str] = set()
        for value in self.disease_names:
            name = " ".join(value.split())
            identity = name.casefold()
            if not name or identity in seen:
                continue
            seen.add(identity)
            names.append(name)
        if len(names) > 25:
            raise ValueError("Danh sách import hỗ trợ tối đa 25 tên bệnh")
        if self.discovery_mode == "import":
            if not names:
                raise ValueError("Chế độ import yêu cầu ít nhất một tên bệnh")
            self.disease_names = tuple(names)
            self.max_items = len(names)
        else:
            self.disease_names = ()
        return self


class RunStage(BaseModel):
    name: RunStageName
    label: str
    state: StageState = StageState.PENDING
    message: str = "Đang chờ"
    current: int = Field(default=0, ge=0)
    total: int = Field(default=0, ge=0)
    started_at: datetime | None = None
    finished_at: datetime | None = None


class RunSnapshot(BaseModel):
    job_id: str
    state: RunState = RunState.QUEUED
    stages: tuple[RunStage, ...]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    report_available: bool = False


class RunStartResponse(BaseModel):
    job_id: str
    state: RunState
