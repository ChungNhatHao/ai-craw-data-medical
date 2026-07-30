# MVP Day 7 — Implementation Report

Status: **DONE — LIVE DATA VALIDATED**

Date: 2026-07-29

## Completed

- Added plugin-owned content-root and title selectors.
- Added a generic content extractor fallback for future sites.
- Removed scripts, styles, navigation, footer, forms and known site chrome.
- Sanitized extracted HTML to an allowlist of semantic content tags.
- Added deterministic Markdown conversion for:
  - headings and paragraphs;
  - nested ordered/unordered lists;
  - links, emphasis, inline code and code blocks;
  - blockquotes and GFM tables.
- Normalized Unicode, whitespace, line endings, URLs and table-cell breaks.
- Added SHA-256 `content_hash` over the final UTF-8 Markdown bytes.
- Added `cleaner_version = 1.0.0` so an algorithm change invalidates an older
  clean checkpoint.
- Persisted `content.html`, `markdown.md` and manifest updates atomically.
- Added database transitions for `cleaning`, `cleaned` and failed cleaning.
- Added recovery that reuses only a version-matched artifact with a valid hash.
- Added `CONTENT_INVALID` for empty or unusable extracted content.

## Cleaning flow

```text
fetched raw checkpoint
  → verify raw manifest and raw hash
  → select plugin content root
      └─ missing → generic extractor fallback
  → remove site chrome and unsafe tags
  → sanitize semantic HTML
  → deterministic Markdown conversion
  → normalize and calculate content hash
  → atomically write content.html + markdown.md
  → atomically update manifest last
  → mark database item cleaned
```

## Automated verification

```text
ruff: passed
mypy: passed
pytest: 48 tests passed

known boilerplate removed: passed
headings/lists/tables/links retained: passed
generic fallback warning: passed
Unicode/hash determinism: passed
atomic artifact set and database checkpoint: passed
valid restart reuse: passed
empty content rejected: passed
cleaner-version checkpoint invalidation: passed
```

One upstream LangGraph pending-deprecation warning remains and does not affect
the Day 7 result.

## Validation on real Day 6 artifacts

Day 7 intentionally ran offline against the two authenticated raw checkpoints
from Day 6; it did not log in or make new website requests.

```text
job: 60cfa667-1e52-485f-b678-c2c0355e161f
items cleaned: 2
restart reused artifact: true
restart hash stable: true
forbidden tags: 0
forbidden UI text markers: 0
warnings: 0

Acrocyanosis:
  markdown characters: 1,026
  content hash: 0f3c9902e3453cfbbc5ed4f9083ee4d38d6478c85267fdfe5f86134d4714af28

Aortic dilatation:
  markdown characters: 3,915
  content hash: baf61b0fd50875ec300bafeb9a620036312e9c996991c13b9bd2157422bf567d
```

The final Markdown retains medical headings, descriptive text, evidence,
references, links and tables. Multi-line table cells use `<br>` so every GFM
table row remains structurally valid.

Both artifact sets contain `raw.html`, masked `screenshot.png`,
`content.html`, `markdown.md` and `manifest.json`. Files use permission `0600`,
manifest hashes match the actual files, state is `cleaned`, cleaner version is
`1.0.0`, and no orphan temporary files remain.

The job still contains one controlled `retryable_failed` non-disease item from
the Day 6 continue-on-error test. This is expected and is unrelated to cleaning.

## Reproduction

```text
.venv/bin/python -m app.plugins.genre_manuals.day7_live_validation
```

