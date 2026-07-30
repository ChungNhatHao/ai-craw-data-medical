# MVP Day 4 — Implementation Report

Status: **DONE — LIVE VALIDATED**

Date: 2026-07-28

## Completed

- Added discovery models and safety policy.
- Added canonical URL normalization.
- Added plugin-scoped stable SHA-256 item IDs.
- Added Genre Manuals disease-link discovery.
- Added next-page detection and pagination loop.
- Added duplicate removal across pages.
- Added visited-page and no-new-item termination.
- Added `max_items` and `max_pages` limits.
- Added SQLite `crawl_items` migration and idempotent upsert.
- Added atomic `disease-list.json` export.
- Added resume-safe rerun test against the same job.

## Discovery flow

```text
classify listing page
  → collect matching disease links
  → canonicalize URLs
  → create plugin-scoped item IDs
  → deduplicate
  → SQLite upsert
  → find unvisited next page
  ├─ found → navigate and repeat
  └─ absent/limit/no-progress → export disease-list.json
```

## Verification

```text
Python: 3.12.13
ruff: passed
mypy: passed
pytest: 36 tests passed
two-page pagination: passed
cross-page duplicate removal: passed
max-items limit: passed
rerun/idempotent persistence: passed
atomic JSON export: passed
public Financial page false disease items: 0
FastAPI migration/readiness smoke: passed
```

During testing, a broad medical URL regex incorrectly included a pagination URL.
The test caught it, and the rule was tightened to explicit disease URL shapes
such as `en_med_*` or `/diseases/{slug}`.

## Live authenticated validation

```text
session valid: true
listing classified as DISEASE_LIST: true
items discovered: 9
unique item IDs: 9
pages visited: 1
stop reason: last_page
safety limits reached: none
required output fields complete: true
orphan temporary export files: 0
```

Live-site findings:

- The observed listing is a hierarchical tree rather than numbered pagination.
- Disease links use multiple legacy URL shapes, including generic root `.htm`
  paths.
- Discovery now scopes extraction to descendants of the currently active
  `#sidemenutree` node. This avoids calculator, financial and global-menu links.
- The active-branch strategy is gated by both `MEDICAL` and `RATINGS`
  breadcrumbs; the public Financial regression discovered 0 false disease items.
- Existing pagination support remains available for layouts that expose a
  next-page control.
- The limited live export is stored at
  `output/jobs/c807eb97-07b8-4b73-8ede-bbd4e13e074e/disease-list.json`.

The live runner is intentionally capped at 25 items and 5 pages.
