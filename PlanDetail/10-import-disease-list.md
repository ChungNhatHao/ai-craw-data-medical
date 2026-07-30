# Import disease-name crawl mode

## Operator UI

Step 1 has two mutually exclusive tabs:

1. `Crawl tự động` retains the existing Medical-tree discovery flow.
2. `Import tên bệnh` accepts up to 25 disease names from a textarea, `.txt`,
   first-column `.csv`, or column A of an `.xlsx` file.

Imported names are trimmed, whitespace-normalized, deduplicated
case-insensitively, and shown with a live valid-name count before submission.
URL, credentials, authorization, extraction, and normalization settings remain
shared between both modes.

The import panel exposes `Tải XLSX mẫu`. The generated workbook contains a
`Disease Name` header in column A, instructions in column B, and example rows.
The XLSX parser accepts at most 2 MB compressed / 10 MB uncompressed, rejects
unsafe archive paths, reads only the first worksheet's column A, removes the
header and duplicates, and enforces the same 25-name limit.

## Execution flow

```text
import disease names
  -> validate and deduplicate (max 25)
  -> authenticate once / reuse protected session
  -> locate #searchTerm ("Start Searching ...")
  -> enter one disease name and submit the site's GET search form
  -> accept exact normalized title matches on the allowlisted domain only
  -> navigate to candidate
  -> deterministic detector confirms disease detail twice
  -> enqueue confirmed DiscoveredItem
  -> fetch -> clean -> parse -> report using the existing pipeline
```

An approximate result is not selected automatically. A missing or
non-disease result is reported in the live discovery-stage message, while
other imported names continue processing. If none are confirmed, the run
stops before fetch with `DISEASE_NOT_CONFIRMED`.

Every import run persists `import-search.json` before fetch. Each requested
name records:

- the query and `#searchTerm` site-search method;
- the search-result URL;
- number of inspected links and exact matches;
- selected URL, when present;
- both disease-detector classifications;
- `matched` or `not_found` status;
- a machine-readable reason code, human-readable reason, and ordered search
  steps.

The report UI shows `Nhật ký import` when this artifact is available.

## API contract

`POST /api/v1/jobs/runs/start` accepts:

```json
{
  "discovery_mode": "import",
  "disease_names": ["Down syndrome", "Sepsis"]
}
```

`discovery_mode` defaults to `automatic`, preserving compatibility with
existing clients. In import mode, `max_items` is set to the normalized unique
name count.

XLSX endpoints:

- `GET /api/v1/jobs/imports/xlsx/template`
- `POST /api/v1/jobs/imports/xlsx/parse`

## Live validation

Job `25b5eccd-ec12-49b8-bf72-bf4097fe34e7` imported `Down syndrome` and
`Sepsis` through the live site search form:

- exact search matches confirmed: 2/2
- fetched: 2/2
- cleaned: 2/2
- structured JSON parsed: 2/2
- failed items: 0
- both report rows contain the complete raw, tab, clean, Markdown, screenshot,
  and disease JSON artifact set

The localhost UI rendered both result rows without a JavaScript page error.

Audit/not-found canary job `1b63d037-02d0-4b4c-97b8-f6966e483169` searched
one valid and one intentionally nonexistent name:

- valid disease: exact match among 58 inspected links and detector confidence
  `1.00` twice;
- nonexistent name: 56 links inspected, zero exact matches, reason code
  `exact_title_not_found`;
- the valid disease continued through fetch, clean, parse, and report;
- `import-search.json` remained downloadable from the final UI;
- XLSX template upload populated two valid names without a browser error.
