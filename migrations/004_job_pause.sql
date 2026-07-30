ALTER TABLE crawl_jobs
ADD COLUMN stop_requested INTEGER NOT NULL DEFAULT 0;

CREATE INDEX idx_crawl_jobs_stop_requested
ON crawl_jobs(status, stop_requested);
