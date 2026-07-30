# MVP Day 5 — Implementation Report

Status: **DONE — LIVE VALIDATED**

Date: 2026-07-28

## Completed

- Added the Day 5 LangGraph item subgraph through `persist_raw`.
- Added a plugin content-ready hook and Genre Manuals DOM readiness check.
- Reclassified the page before and after the readiness wait; only a confirmed
  `DISEASE_DETAIL` can be persisted.
- Added full-page PNG capture with plugin-owned sensitive-region masking.
- Added atomic `raw.html`, `screenshot.png` and `manifest.json` writes.
- Added SHA-256 and byte-size validation for every raw artifact.
- Added safe slug plus 12-character item ID artifact directories.
- Added `crawl_attempts` migration and per-attempt success/failure history.
- Added item transitions: `discovered → fetching → fetched` and retryable
  failure checkpoint.
- Added exponential retry for network, navigation, empty-content and storage
  failures.
- Added restart reconciliation: a valid manifest and matching hashes move the
  item to `fetched` without browser navigation.

## Automated verification

```text
ruff: passed
mypy: passed
pytest: 39 tests passed
raw HTML atomic write: passed
PNG atomic write: passed
manifest/checksum validation: passed
network timeout then retry: passed
attempt history failure → success: passed
restart after raw write without refetch: passed
LangGraph persist_raw checkpoint: passed
```

One upstream LangGraph pending-deprecation warning remains; it does not affect
the Day 5 result.

## Live authenticated validation

```text
session valid: true
disease detail confirmed: true
classifier confidence: 1.0
raw HTML: 30,463 bytes
masked screenshot: 311,257 bytes
checksum validation: passed
attempt records: 1
second invocation reused artifact: true
file permissions: 0600
orphan temporary files: 0
```

Live job:

`7e2c3c05-b378-4c9f-851d-d93b76df258c`

Artifact directory:

`output/jobs/7e2c3c05-b378-4c9f-851d-d93b76df258c/items/acrocyanosis--83c6fd41cdf7`

## Security validation

Visual review found that the earlier screenshot mask covered the Logout control
but not the adjacent account identifier. The plugin now masks the complete
`#genre-shortcuts` account region before Playwright captures evidence. All
incomplete-mask artifacts were removed and their test jobs marked failed. The
retained screenshot was visually verified as a disease detail page with the
complete account region covered.

Raw HTML and screenshot artifacts are Git-ignored and written with permission
`0600`. Credentials, cookies and storage state are not included in the manifest
or runner output.

## Reproduction

```text
PLAYWRIGHT_BROWSERS_PATH=/tmp/aicrawler-playwright \
  .venv/bin/python -m app.plugins.genre_manuals.day5_live_validation
```

The live runner is restricted to one discovered disease item.
