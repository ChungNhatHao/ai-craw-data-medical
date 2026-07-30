CREATE TABLE crawl_items (
    job_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    source_url TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    title_hint TEXT,
    discovery_page TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'discovered',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    content_hash TEXT,
    previous_content_hash TEXT,
    last_error_code TEXT,
    artifact_dir TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (job_id, item_id),
    FOREIGN KEY (job_id) REFERENCES crawl_jobs(id)
);

CREATE INDEX idx_crawl_items_status ON crawl_items(job_id, status);
CREATE INDEX idx_crawl_items_canonical_url ON crawl_items(canonical_url);

