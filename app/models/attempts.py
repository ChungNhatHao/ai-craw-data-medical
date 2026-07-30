from datetime import datetime

from pydantic import BaseModel


class CrawlAttempt(BaseModel):
    id: int
    job_id: str
    item_id: str
    attempt_no: int
    stage: str
    started_at: datetime
    finished_at: datetime | None = None
    result: str
    error_code: str | None = None
    error_message: str | None = None
