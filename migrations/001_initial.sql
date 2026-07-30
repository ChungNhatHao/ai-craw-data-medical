CREATE TABLE crawl_jobs (
    id TEXT PRIMARY KEY,
    plugin TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);

CREATE INDEX idx_crawl_jobs_status ON crawl_jobs(status);

