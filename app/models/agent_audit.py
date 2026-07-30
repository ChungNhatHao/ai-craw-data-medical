from datetime import datetime

from pydantic import BaseModel, Field

SHA256_PATTERN = r"^[0-9a-f]{64}$"


class AgentDecisionRecord(BaseModel):
    id: int = Field(ge=1)
    job_id: str = Field(min_length=1)
    item_id: str | None = None
    agent_name: str = Field(min_length=1)
    page_fingerprint: str | None = None
    decision: dict[str, object]
    confidence: float | None = Field(default=None, ge=0, le=1)
    created_at: datetime


class ModelCallRecord(BaseModel):
    id: int = Field(ge=1)
    job_id: str = Field(min_length=1)
    item_id: str | None = None
    agent_name: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    input_hash: str = Field(pattern=SHA256_PATTERN)
    output_hash: str | None = Field(default=None, pattern=SHA256_PATTERN)
    latency_ms: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cached: bool = False
    status: str = Field(min_length=1)
    error_code: str | None = None
    created_at: datetime
