CREATE TABLE category_item_provenance (
    job_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    root_query TEXT NOT NULL,
    parent_url TEXT,
    menu_path_json TEXT NOT NULL,
    depth INTEGER NOT NULL CHECK (depth >= 0 AND depth <= 8),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (job_id, item_id, root_query, menu_path_json),
    FOREIGN KEY (job_id, item_id) REFERENCES crawl_items(job_id, item_id)
);

CREATE INDEX idx_category_item_provenance_job
ON category_item_provenance(job_id, item_id, root_query);
