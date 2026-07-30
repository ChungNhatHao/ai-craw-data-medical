ALTER TABLE crawl_items ADD COLUMN snapshot_hash TEXT;
ALTER TABLE crawl_items ADD COLUMN previous_snapshot_hash TEXT;
ALTER TABLE crawl_items ADD COLUMN baseline_job_id TEXT;
ALTER TABLE crawl_items ADD COLUMN change_status TEXT;
ALTER TABLE crawl_items ADD COLUMN changed_components_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE crawl_items ADD COLUMN checked_at TEXT;

CREATE INDEX idx_crawl_items_incremental_baseline
ON crawl_items(item_id, change_status, updated_at);
