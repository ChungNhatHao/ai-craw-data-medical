# MVP Day 9 — Integration and Release Report

Status: **DONE — TECHNICAL RELEASE CANDIDATE VALIDATED**

Date: 2026-07-29

Production release gate: **D-02 SATISFIED — OWNER CONFIRMED 2026-07-29**

## Completed

- Added validation repair through the structured client contract.
- Enforced at most one repair call per parsing attempt.
- Revalidated schema and source grounding after repair.
- Added `report.json` with:
  - job status and counts;
  - every successful and failed item;
  - artifact completeness and content hash;
  - actionable last error code.
- Added final `job.json` with report size and SHA-256.
- Persisted report first and job manifest last, both atomically.
- Added API endpoints:
  - `POST /api/v1/jobs`;
  - `GET /api/v1/jobs/{job_id}`;
  - `GET /api/v1/jobs/{job_id}/report`.
- Added report-availability status and correct 404 behavior.
- Added a three-item fixture E2E replay:
  - two complete raw → clean → parse → report exports;
  - one controlled page-type error;
  - successful items retained and failed item included in report.
- Added configurable parser timeout, call budget and input budget.
- Updated `.env.example` without credential values.
- Replaced the foundation README with an MVP operator runbook.

## Final integrated flow

```text
authenticated discovery/fetch checkpoints
  → validate raw evidence
  → clean semantic HTML and Markdown
  → parse schema v1
      ├─ valid + grounded → continue
      └─ invalid → repair once
           ├─ valid + grounded → continue
           └─ invalid → retain last good JSON + failed queue
  → persist disease.json + item manifest
  → aggregate every item status
  → persist report.json
  → persist job.json with report hash
  → expose status/report through internal API
```

## Automated verification

```text
ruff: passed
mypy: passed
pytest: 57 tests passed

repair applied once: passed
ungrounded repair rejected: covered by grounding tests
last valid JSON protected: passed
API create/status/report: passed
API missing job/report behavior: passed
localhost Uvicorn health/readiness smoke: passed
3-item E2E replay: passed
2 successful complete artifact sets: passed
1 failed item retained in report: passed
atomic report/job manifest: passed
report hash verification: passed
```

One upstream LangGraph pending-deprecation warning remains and does not affect
the release-candidate result.

## Validation against the retained real job

Day 9 finalized the authenticated job built through Days 2–8. It reused the
retained checkpoints and made no new website request.

```text
job: 60cfa667-1e52-485f-b678-c2c0355e161f
status: completed_with_errors
total items: 3
successful items: 2
failed items: 1
complete MVP artifact sets: 2
failed error: PAGE_TYPE_UNKNOWN

report reload validation: passed
report hash matches job manifest: passed
API job status: HTTP 200
API job report: HTTP 200
API report_available: true
```

The single failed item is the controlled same-domain non-disease URL introduced
on Day 6 to prove continue-on-error behavior. It has no content artifacts and
is correctly visible in the final report.

Each successful real item contains:

```text
raw.html
content.html
markdown.md
disease.json
screenshot.png
manifest.json
```

The authenticated workflow has cumulative live evidence for login/session,
navigation, discovery and batch fetch from Days 2–6. Days 7–9 then replay the
same retained evidence offline through Markdown, structured JSON and final
report export. The fixture suite additionally proves the full downstream
pipeline in one E2E test.

## Definition of Done assessment

| MVP criterion | Result |
|---|---|
| Auto login and session reuse | PASS — Day 2 live |
| Discovery within configured limits | PASS — Day 4 live |
| Page detection loop before fetch | PASS — Day 3 live |
| Batch crawl and continue-on-error | PASS — Days 5–6 live |
| Raw/Markdown/JSON/PNG/manifest per success | PASS — 2 real items |
| Pydantic schema and provenance | PASS |
| Accurate job report | PASS |
| Unit/integration/E2E quality gates | PASS — 57 tests |
| Secret excluded from published code/docs | PASS |
| Documented target-site authorization | PASS — owner confirmed 2026-07-29 |

## Release decision

The software is a **technical MVP release candidate**. It is suitable for
internal review and controlled offline/replay demonstrations.

The owner confirmed permission to automate the target account and retain
HTML/PNG/Markdown/JSON for internal purposes on 2026-07-29. Controlled live
crawls may proceed. The API must remain local/internal because the MVP has no
API authentication.

## Known limitations

- `POST /jobs` records a queued job but does not launch a background worker.
- Deterministic rules are the default parser; a real model provider is not yet
  enabled.
- D-02 must be reconfirmed if account scope, contract or site terms change.
- Migration backup/restore and packaged rollback image remain release-ops work.
- Docker, incremental versions, Vision fallback and crash injection are V2.

## Reproduction

```text
.venv/bin/python -m app.plugins.genre_manuals.day9_live_validation
```
