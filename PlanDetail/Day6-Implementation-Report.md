# MVP Day 6 — Implementation Report

Status: **DONE — LIVE VALIDATED**

Date: 2026-07-29

## Completed

- Added database-backed select-next for `discovered` items.
- Excluded `fetched`, `completed` and failed-queue items from normal selection.
- Added batch orchestration with a per-item atomic checkpoint.
- Added continue-on-error behavior for item-scoped crawler failures.
- Added job-level stop behavior for authentication/session/CAPTCHA failures.
- Added persistent `stop_requested` and `pausing/paused` job states.
- Added graceful pause checks between items, never during atomic artifact writes.
- Added resume that retains item attempt history and clears only the stop flag.
- Added `completed_with_errors` terminal status.
- Added startup recovery for interrupted `fetching` items:
  - valid raw manifest/hash → advance to `fetched`;
  - missing/invalid raw → reset to `discovered`.
- Added status counts and remaining-queue reporting.

## Batch state flow

```text
resume job
  → reconcile interrupted fetching items
  → check pause request
  → select next discovered item
      ├─ success → raw checkpoint → next item
      ├─ item error → failed queue → next item
      └─ auth/block → pause job
  → queue empty
      ├─ no failures → completed
      └─ failures → completed_with_errors
```

## Automated verification

```text
ruff: passed
mypy: passed
pytest: 43 tests passed
continue after one item failure: passed
pause after safe checkpoint: passed
resume skips fetched item: passed
fetching + valid raw recovery: passed
fetching + missing raw recovery: passed
attempt history retained: passed
```

One upstream LangGraph pending-deprecation warning remains and does not affect
the Day 6 result.

## Live authenticated validation

The live smoke used two real disease items plus one controlled same-domain
non-disease URL to exercise continue-on-error without modifying website data.

```text
session valid in both phases: true

phase 1:
  processed: 1
  status: paused
  reason: max_items
  remaining: 2
  browser/context cleanup: passed

phase 2:
  opened a new browser/context
  processed: 2
  fetched: 1
  failed: 1
  controlled error: PAGE_TYPE_UNKNOWN
  status: completed_with_errors
  reason: queue_empty
  browser/context cleanup: passed

final:
  fetched items: 2
  retryable failed items: 1
  valid raw artifact sets: 2
  first item attempt records: 1
```

The first item retaining exactly one attempt proves phase 2 did not crawl it
again.

Live job:

`60cfa667-1e52-485f-b678-c2c0355e161f`

Artifact root:

`output/jobs/60cfa667-1e52-485f-b678-c2c0355e161f/items`

## Security correction

Visual review showed the initial account mask covered only the Logout control,
not the adjacent account identifier. The mask now targets the complete
`#genre-shortcuts` account region, with an ancestor-list fallback. A sanitized
fixture prevents regression.

The incomplete-mask artifact set was removed and its test job marked failed.
Both retained live screenshots were visually checked with the complete account
region covered. All retained raw, screenshot and manifest files use permission
`0600`, have valid SHA-256 hashes and have no orphan temporary files.

## Reproduction

```text
PLAYWRIGHT_BROWSERS_PATH=/tmp/aicrawler-playwright \
  .venv/bin/python -m app.plugins.genre_manuals.day6_live_validation
```
