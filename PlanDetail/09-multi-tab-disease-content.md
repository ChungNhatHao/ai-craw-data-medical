# Multi-tab disease content

## Scope

Each confirmed Genre Manuals disease page is captured from four source tabs:

1. `Info`
2. `Life/DD/TPD`
3. `IP`
4. `Health`

`Info` is present in the initial document. The other tabs are loaded by the
site's allowlisted `.html.ajax` endpoint after a browser click. Browser/session
controls remain in the backend.

## Data flow

```text
confirmed disease page
  -> capture Info DOM fragment
  -> click Life/DD/TPD, IP, Health
  -> find unique read-only detail links in each tab
  -> GET allowlisted same-domain detail articles
  -> persist tabs-raw.json
  -> BeautifulSoup sanitize each tab and detail fragment
  -> convert each fragment to Markdown
  -> extract table rows deterministically
  -> persist tabs.json
  -> embed tabs in disease.json schema 1.1
  -> expose tabs in report API and operator UI
```

The medical `disease` fields continue to be extracted from `Info`. Underwriting
tables from the other tabs are retained as source-tab content instead of being
misclassified as symptoms, diagnosis, or treatment.

The detail collector is intentionally read-only. It follows only
`a.genrePopup[href]` targets on the Genre Manuals allowlist and deduplicates
identical URLs. Labels containing `Edit`, the `Edit note` action, and the `+`
cart input are never executed. Detail responses are reduced to
`.genrearticle` before persistence, excluding account and navigation chrome.
Expandable `References` content remains part of the Info tab text and tables.

## Artifacts

- `tabs-raw.json`: captured tab fragments, article-only related-detail
  fragments, and provenance.
- `tabs.json`: BeautifulSoup-cleaned text, Markdown, table rows, hashes, and
  per-tab/per-detail warnings.
- `disease.json`: schema `1.1`, including the same clean tab collection.

For Genre Manuals, a report item is complete only when both tab artifacts are
present alongside the existing raw, clean, screenshot, and disease artifacts.

## Live validation

Job `01f264c8-e326-4cd6-8d7a-7dc90353376f` completed with one parsed item and
zero failures. It captured all four tabs:

- Info: 1087 characters
- Life/DD/TPD: 157 characters
- IP: 60 characters
- Health: 110 characters

All tabs were available, table rows were preserved, and `disease.json`
contained four embedded tab objects. The read-only collector also captured 11
unique related articles: 6 from Life/DD/TPD, 1 from IP, and 4 from Health.
Every detail was available and cleaned successfully. No Edit/Edit note label
or cart action appeared in the clean output.
