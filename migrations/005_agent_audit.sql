CREATE TABLE agent_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    item_id TEXT,
    agent_name TEXT NOT NULL,
    page_fingerprint TEXT,
    decision_json TEXT NOT NULL,
    confidence REAL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (job_id) REFERENCES crawl_jobs(id)
);

CREATE INDEX idx_agent_decisions_job_agent
ON agent_decisions(job_id, agent_name, id);

CREATE TABLE model_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    item_id TEXT,
    agent_name TEXT NOT NULL,
    model_id TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    output_hash TEXT,
    latency_ms INTEGER NOT NULL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cached INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    error_code TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (job_id) REFERENCES crawl_jobs(id)
);

CREATE INDEX idx_model_calls_job_agent
ON model_calls(job_id, agent_name, id);

CREATE INDEX idx_model_calls_cache
ON model_calls(input_hash, prompt_version, model_id, status);
