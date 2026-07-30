CREATE TABLE crawl_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    attempt_no INTEGER NOT NULL,
    stage TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    result TEXT NOT NULL,
    error_code TEXT,
    error_message TEXT,
    details_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (job_id, item_id) REFERENCES crawl_items(job_id, item_id),
    UNIQUE (job_id, item_id, attempt_no, stage)
);

CREATE INDEX idx_crawl_attempts_item
ON crawl_attempts(job_id, item_id, stage, attempt_no);
