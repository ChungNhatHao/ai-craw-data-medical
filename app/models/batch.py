from pydantic import BaseModel, Field

from app.models.crawl import JobStatus


class BatchPolicy(BaseModel):
    max_items: int = Field(default=100, ge=1)


class BatchResult(BaseModel):
    job_id: str
    status: JobStatus
    processed_count: int = Field(ge=0)
    fetched_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    recovered_count: int = Field(ge=0)
    remaining_count: int = Field(ge=0)
    stopped_reason: str
