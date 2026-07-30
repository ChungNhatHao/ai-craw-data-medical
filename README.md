# AI Medical Crawler

MVP release candidate for an authenticated, plugin-based medical content
crawler. The pipeline discovers disease pages, confirms page type, checkpoints
raw evidence, cleans Markdown, creates schema-validated disease JSON and emits
an auditable job report.

This tool collects source material. It does not diagnose disease or provide
medical advice.

## Requirements

- Python 3.12
- Playwright Chromium
- Authorization to automate and retain content from the target website

## Local setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
playwright install chromium
cp .env.example .env
```

Put credentials only in `.env`. Never commit `.env`, session state, logs or
output artifacts. These paths are already excluded by `.gitignore`.

## Configuration

Important runtime limits:

| Variable | Default | Purpose |
|---|---:|---|
| `CRAWL_MAX_ITEMS` | 1000 | Maximum discovered items |
| `CRAWL_MAX_PAGES` | 100 | Maximum listing pages |
| `FETCH_MAX_ATTEMPTS` | 3 | Per-item network attempts |
| `PARSE_TIMEOUT_SECONDS` | 30 | Structured parsing timeout |
| `PARSE_MAX_MODEL_CALLS` | 40 | Maximum chunk/model calls |
| `PARSE_MAX_INPUT_CHARS` | 200000 | Parser input budget |
| `CAPTURE_SCREENSHOT` | true | Save masked evidence PNG |

The API binds to `127.0.0.1` by default. Keep it internal: the MVP API has no
authentication or authorization layer.

## Run the API

```bash
medical-crawler --host 127.0.0.1 --port 8000
```

If Chromium was installed in a shared/custom directory:

```bash
PLAYWRIGHT_BROWSERS_PATH=/tmp/aicrawler-playwright \
  medical-crawler --host 127.0.0.1 --port 8000
```

Open the operator UI:

```text
http://127.0.0.1:8000/
```

The UI accepts the authorized target URL, username, password and an item limit.
After clicking **Thực thi crawler**, it polls the backend and displays these
observable stages:

```text
validate → authenticate → navigate → discover
         → fetch → clean → parse → report
```

When the run reaches a terminal state, the page shows success/error counts and
download links for raw HTML, cleaned HTML, Markdown, disease JSON and the
masked screenshot. The password is cleared from the browser form immediately
after the backend accepts the run and is never returned by an API response.

Endpoints:

- `GET /api/v1/health/live`
- `GET /api/v1/health/ready`
- `POST /api/v1/jobs`
- `GET /api/v1/jobs/{job_id}`
- `GET /api/v1/jobs/{job_id}/report`
- `POST /api/v1/jobs/runs/start`
- `GET /api/v1/jobs/runs/{job_id}`
- `GET /api/v1/jobs/{job_id}/items/{item_id}/artifacts/{file_name}`

Create a queued job:

```bash
curl -sS -X POST http://127.0.0.1:8000/api/v1/jobs \
  -H 'content-type: application/json' \
  -d '{"plugin":"genre_manuals"}'
```

Run a real localhost Uvicorn health smoke:

```bash
bash scripts/smoke_api.sh
```

The MVP create endpoint records the job. Browser execution is currently
started through the internal orchestration/validation commands, not an API
background worker.

## Validation commands

Public browser/runtime checks:

```bash
python -m app.browser.smoke
python -m app.plugins.genre_manuals.smoke
python -m app.plugins.genre_manuals.navigation_smoke
```

Authenticated session creation/reuse:

```bash
python -m app.plugins.genre_manuals.login
```

Offline validation against retained checkpoints:

```bash
python -m app.plugins.genre_manuals.day7_live_validation
python -m app.plugins.genre_manuals.day8_live_validation
python -m app.plugins.genre_manuals.day9_live_validation
```

Day 9 validates final report generation and the internal API without making a
new website request.

## Output

```text
output/jobs/{job_id}/
├── job.json
├── report.json
└── items/{slug}--{item_id_12}/
    ├── manifest.json
    ├── raw.html
    ├── content.html
    ├── markdown.md
    ├── disease.json
    └── screenshot.png
```

Successful item files and job-level JSON files are written atomically with
permission `0600`. Manifest and report entries contain SHA-256 hashes.

## Quality gates

```bash
ruff check app tests
mypy app
pytest
```

The fixture E2E test exercises three items: two complete exports and one
controlled page-type failure. The failed item remains visible in `report.json`
without stopping successful items.

## Recovery behavior

- A valid raw, clean or parsed checkpoint is reused after restart.
- Cleaner/parser/schema/model version changes invalidate only the affected
  derived checkpoint.
- Invalid structured output may be repaired once when the configured client
  supports repair.
- Ungrounded output is rejected and cannot overwrite the last valid document.
- Batch errors remain in a failed queue and are included in the final report.

## Known limitations

- D-02 was owner-confirmed for internal automation/content retention on
  2026-07-29; reconfirm it if account scope, contract or site terms change.
- The internal API has no authentication and must not be exposed publicly.
- `POST /jobs` does not yet launch a distributed/background worker.
- The MVP uses deterministic rule parsing by default. A real model provider
  must implement `StructuredModelClient` and be validated before enablement.
- CAPTCHA/MFA requires operator action; the crawler does not bypass controls.
- Vision fallback, incremental version history, Docker packaging and
  crash-injection hardening are V2 work.
- One upstream LangGraph pending-deprecation warning is currently present.

Detailed architecture, decisions and daily evidence are in
[PlanDetail/README.md](PlanDetail/README.md).

# ai-craw-data-medical
