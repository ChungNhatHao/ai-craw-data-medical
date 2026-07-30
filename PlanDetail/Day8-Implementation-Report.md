# MVP Day 8 — Implementation Report

Status: **DONE — LIVE DATA VALIDATED**

Date: 2026-07-29

## Completed

- Implemented the approved disease document schema v1 with Pydantic.
- Added required source provenance:
  - plugin, source URL and canonical URL;
  - retrieval timestamp, content hash and source language.
- Added versioned parser prompt `parser_v1.md` (`prompt_version = 1.0.0`).
- Added a replaceable async `StructuredModelClient` contract.
- Added deterministic rules parsing as the zero-external-call MVP client.
- Added heading-based Markdown chunking with stable order.
- Added deterministic field merge and duplicate removal.
- Added extraction for disease name, aliases, summary and supported medical
  table fields.
- Added a strict no-hallucination guard: every returned medical value must be
  grounded in the source Markdown.
- Added explicit `missing_field:*` warnings while preserving absent values as
  `null` or `[]`.
- Added parser limits for timeout, maximum calls and input character budget.
- Added schema hash, parser/prompt/model version checkpoint validation.
- Added atomic `disease.json` persistence followed by manifest and database
  state updates.
- Added `parsing`, `parsed` and failed parsing database transitions.
- Added recovery that reuses only a valid version-matched JSON artifact.
- Added `LLM_OUTPUT_INVALID` and `PARSE_TIMEOUT` error categories.
- Protected the last good document from invalid replacement output.

Final versions:

```text
schema_version: 1.0
schema_hash: fc137a62dacda688446a4dd53fe70f0c26fa337c005244ce60b2bc1fa852b276
parser_version: 1.0.3
prompt_version: 1.0.0
```

## Structured parsing flow

```text
validated Markdown checkpoint
  → verify content hash and cleaner version
  → split by Markdown heading
  → enforce input/call/timeout budgets
  → parse each chunk through StructuredModelClient
  → deterministic merge and deduplication
  → validate Pydantic disease schema
  → reject any value not grounded in source Markdown
  → add warnings for absent source fields
  → atomically write disease.json
  → atomically update manifest last
  → mark database item parsed
```

## Automated verification

```text
ruff: passed
mypy: passed
pytest: 52 tests passed

heading chunk order: passed
deterministic merge: passed
name/aliases/summary/table field extraction: passed
missing fields remain null/empty: passed
schema hash determinism: passed
source/provenance required: passed
atomic disease JSON checkpoint: passed
restart reuse: passed
hallucinated fake-model output rejected: passed
last valid disease.json not overwritten: passed
```

One upstream LangGraph pending-deprecation warning remains and does not affect
the Day 8 result.

## Validation on real Day 7 Markdown

Day 8 ran offline against the two real Markdown checkpoints from Day 7. No
website request or external model call was made.

```text
job: 60cfa667-1e52-485f-b678-c2c0355e161f
items parsed: 2
method: rules
external model calls: 0
restart reused artifact: true
grounding guard: passed (2/2)
source content hash: matched (2/2)
disease JSON hash: matched (2/2)
database: parsed=2, controlled retryable_failed=1

Acrocyanosis:
  extracted: name, aliases, causes, prognosis
  disease.json SHA-256:
    a6e6e438f01dbaa72be7180d71a18ddf334305ea4d1971d714946ea470775de3

Aortic dilatation:
  extracted: name, aliases, summary, causes, symptoms, treatment, prognosis
  disease.json SHA-256:
    4f7383015bd7733bf7b54ab2b2c925815de229790c5ba46b86372271efed1980
```

Fields absent from each source remain `null`/`[]` and are listed in
`parse_metadata.warnings`; the parser does not infer medical facts.

During implementation, parser versions were deliberately advanced while
intro/alias/warning behavior was refined. This produced four retained parse
attempt records per real item. The final repeat reused parser `1.0.3` without a
new attempt, proving version-aware recovery.

Both final `disease.json` and manifest files use permission `0600`; all hashes
match and no orphan temporary files remain.

## Reproduction

```text
.venv/bin/python -m app.plugins.genre_manuals.day8_live_validation
```

