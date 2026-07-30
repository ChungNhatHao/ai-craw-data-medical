# MVP Day 3 — Implementation Report

Status: **DONE — LIVE VALIDATED**

Date: 2026-07-28

## Completed

- Added `PageType`, `PageClassification`, `NavigationCandidate` and loop policy.
- Added mandatory `NavigationDetectionLoop`.
- Added disease-detail confidence gate.
- Added current-page fingerprints and visited candidate protection.
- Added max hops, repeated fingerprint and no-progress guards.
- Added routing for disease detail, list/menu, login, blocked and unknown pages.
- Added allowlisted popup dismissal.
- Added candidate navigation with timeout and domain validation.
- Added Genre Manuals classifier based on observed public DOM:
  `#content`, `ul.breadcrumb`, `#sidemenutree`, `h2.pageTitle`,
  `.genrearticle`.

## Guaranteed behavior

```text
DISEASE_DETAIL       → allow fetch/crawl
DISEASE_LIST         → choose unvisited candidate and loop
HOME_OR_MENU         → choose menu candidate and loop
LOGIN                → AUTH_SESSION_EXPIRED
BLOCKED_OR_CAPTCHA   → pause/operator error
UNKNOWN              → retry until loop guard
```

No branch except `DISEASE_DETAIL` can proceed to content crawl.

## Verification

```text
Python: 3.12.13
ruff: passed
mypy: passed
pytest: 32 tests passed
home → list → detail: passed in 3 hops
unknown/no-progress guard: passed
login/blocked routing: passed
popup dismissal: passed
```

Browser smoke checks:

- Public home page classified as `LOGIN`: passed.
- Public financial article classified as non-detail `HOME_OR_MENU`: passed.
- Stored authenticated session validation: passed.
- Live detection loop reached a confirmed disease detail in 6 hops.
- Five unique candidates were visited; no candidate repeated.
- Final disease detail confidence: `1.0`.

## Live-site findings and fixes

- The authenticated menu is hierarchical:
  `Home → Medical → Ratings → category → subgroup → disease`.
- Real disease URLs are not limited to the earlier `en_med_*` assumption.
- The classifier now combines the stable `MEDICAL → RATINGS` breadcrumb,
  title and aggregated `.genrearticle` content.
- Empty category pages with an expanded active menu branch are classified as
  `DISEASE_LIST`, not disease detail.
- Candidate ranking now scopes `Ratings` to the Medical tree and follows the
  currently expanded menu branch. This prevents navigation into similarly
  named Occupations or news links.

## Reproduction

```text
PLAYWRIGHT_BROWSERS_PATH=/tmp/aicrawler-playwright \
  .venv/bin/python -m app.plugins.genre_manuals.live_validation
```

The runner emits only sanitized counts/status metadata and never prints
credentials, cookies or page HTML.
