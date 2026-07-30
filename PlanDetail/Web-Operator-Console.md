# Web Operator Console

Status: **IMPLEMENTED — LOCAL UI VALIDATED**

Date: 2026-07-29

## Operator flow

```text
Open http://127.0.0.1:8000/
  → enter authorized HTTPS URL
  → enter username/password
  → choose maximum disease items (1–10)
  → confirm automation/content-retention authorization
  → click "Thực thi crawler"
  → backend returns job ID and clears password from the form
  → UI polls the run snapshot
      01 validate request
      02 authenticate/reuse session
      03 navigate until DISEASE_DETAIL
      04 discover unique disease items
      05 fetch raw HTML + masked screenshot
      06 clean semantic HTML + Markdown
      07 parse schema v1 disease JSON
      08 generate report + final manifest
  → terminal result
      ├─ completed
      ├─ completed_with_errors
      └─ failed with classified error
  → show counts, item statuses and artifact download links
```

## UI components

- Target URL input restricted to HTTPS on `genre-manuals.com`.
- Username and password fields with password reveal control.
- Safe item-limit slider from 1 to 10.
- Required D-02 authorization confirmation.
- Backend readiness indicator.
- Eight-stage timeline with state, message and progress.
- Error panel with sanitized error code/message.
- Final summary cards and per-item artifact table.
- Responsive desktop/mobile layout.

## Credential boundary

- Request fields use Pydantic `SecretStr`.
- Username/password are not persisted in SQLite, report or job manifest.
- API responses never contain credential fields.
- Password is cleared from the browser after run acceptance.
- Session filenames contain only a truncated SHA-256 of the username.
- Session files retain the existing restricted-permission storage behavior.
- Only one live browser run is permitted per process.

## API

```text
POST /api/v1/jobs/runs/start
GET  /api/v1/jobs/runs/{job_id}
GET  /api/v1/jobs/{job_id}
GET  /api/v1/jobs/{job_id}/report
GET  /api/v1/jobs/{job_id}/items/{item_id}/artifacts/{file_name}
```

Artifact download is restricted to an allowlist:

```text
manifest.json
raw.html
content.html
markdown.md
disease.json
screenshot.png
```

## Validation

- Desktop Chromium visual check: passed.
- Mobile Chromium 390 px visual check: passed.
- Root HTML, CSS and JavaScript delivery: passed.
- Run start/progress API contract: passed.
- Credential absent from HTML/API response: passed.
- External domain and missing D-02 confirmation rejection: passed.
- Ruff, Mypy and full pytest suite: passed.

The owner subsequently confirmed D-02 authorization on 2026-07-29. The operator
may now tick the confirmation and start a controlled live run. The visual
validation itself did not submit credentials or make a target-site request.
