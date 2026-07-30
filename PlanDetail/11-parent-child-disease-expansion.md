# Parent-child disease category expansion plan

## Implementation status — completed 2026-07-29

Phases A through F have been implemented and integrated into the live
pipeline.

- Contracts, hard limits, reason codes, and the additive multi-path
  provenance migration are complete.
- Safe exact-first search matching and the constrained singular/plural
  category fallback are complete.
- Bounded breadth-first category traversal, direct-child extraction,
  canonical deduplication, stable detail confirmation, and partial-limit
  handling are complete.
- Imported category results now feed the existing fetch, clean, parse, and
  report pipeline; category pages remain provenance/group nodes only.
- The import UI includes the expansion toggle and three safety limits. Final
  results are grouped by imported root and menu path, with a downloadable
  category audit.
- Automated validation passes: `110 passed`, Ruff clean, and strict Mypy
  clean across 95 source files.

Live acceptance run:

```text
Job: d9560210-87d2-4a53-9304-8f3d18c1e36d
Imported root: Cardiac arrhythmia
Search strategy: singular_plural_category
Category: Cardiac arrhythmias
Confirmed disease details: 7
Fetch / clean / parse: 7 / 7 / 7
Failed items: 0
Category limits reached: none
Provenance paths: 7
```

The live report excludes the category from disease rows, contains one
provenance path for every child, and records a complete artifact set for all
seven diseases. A headless operator-UI check rendered one category group,
seven disease rows, the category-audit link, and no JavaScript errors.

### Autocomplete AI selection extension

The imported-name search now waits for the website autocomplete dropdown and
collects up to 20 unique suggestions. A bounded Gemini autocomplete-selection
agent receives only the imported name plus candidate IDs and labels. It cannot
invent a name or URL, and the existing exact/singular-plural matcher plus page
classifier still validates its selection.

Every `import-search.json` attempt now includes:

- all autocomplete suggestions;
- selected suggestion;
- decision source and confidence;
- structured reason code;
- operator-readable selection reason.

The final UI renders these values in `Quyết định chọn tên bệnh`. Gemini
failures, low-confidence selections, missing API configuration, ambiguous
suggestions, and empty dropdowns all fall back to the original imported name
and are recorded explicitly.

Live autocomplete canary:

```text
Job: ec084e03-4925-4140-b38b-d20c6ca05240
Suggestions collected: 2
Selected: Cardiac arrhythmias
Decision source: gemini
Confidence: 0.95
Reason code: singular_plural
Confirmed child diseases: 7
Final result: 7 successful, 0 failed
```

The operator UI displayed the selected suggestion, confidence, reason, and
seven disease rows without JavaScript errors. The final prompt requests
Vietnamese reasons while preserving medical names in their original language.

### Ambiguous autocomplete expansion

Autocomplete decisions now support one or many candidate IDs. When Gemini can
identify one safe match, only that name is searched. When it returns
`ambiguous`, every plausible suggestion (maximum 10) is searched and validated
independently, even if the aggregate ambiguity confidence is below the normal
single-selection threshold.

The crawler still does not blindly accept all dropdown entries:

- Gemini excludes clearly unrelated suggestions;
- selected IDs must exist in the observed dropdown;
- every selected name goes through exact result matching and page
  classification;
- category/detail pages use the existing bounded traversal;
- canonical URLs are deduplicated before fetch;
- invalid candidates are retained in the audit but do not enter crawl items.

`import-search.json` preserves backward-compatible singular fields and adds
`autocomplete_selected_names` plus `selected_urls`. The UI highlights every
selected suggestion and displays the combined Vietnamese decision reason.

### Autocomplete alias resolution

Genre Manuals autocomplete labels may use `alias - canonical disease`, while
the search-result page exposes only the canonical disease title. The crawler
now preserves the full selected alias for audit/UI but resolves the final
space-delimited ` - ` segment before submitting and matching the search.
Hyphenated medical names without surrounding spaces, such as `COVID-19`, are
left unchanged. Multiple aliases resolving to the same normalized canonical
name are deduplicated before navigation.

Live regression:

```text
Job: 3c9cea18-d48c-45be-b47e-c139de911f9c
Imported: Angina pectoris
Selected alias: Angina pectoris - Coronary artery disease
Resolved search name: Coronary artery disease
Selected URL: https://www.genre-manuals.com/cad.htm
Result: 1 confirmed, 1 fetched, 1 cleaned, 1 parsed, 0 failed
Tabs: Info, Life/DD/TPD, IP, Health
```

Alias matching is also available as an explicit deterministic search strategy
named `alias_exact`. It runs after a full exact-name match and before
singular/plural fallback. The imported query must equal a complete alias
segment before the space-delimited ` - ` separator; substring matches are
rejected. Multiple alias matches pointing to different canonical URLs return
`ambiguous_alias_results` instead of selecting arbitrarily.

### Grounding repair retry

Agentic extraction prompt/parser version `1.1.0` adds one bounded repair call
when Gemini returns a `source_quote` that is absent from BeautifulSoup-cleaned
content. The second prompt explicitly requires verbatim quotes, preserves the
same cleaned input boundary, and instructs the model to omit unsupported
fields. A second invalid response still fails closed with `GROUNDING_FAILED`;
no ungrounded value can reach `disease.json`.

Live regression:

```text
Job: 03b2612c-ea2d-401a-b272-cd635c2cc18d
Disease: Atrial fibrillation
Agentic parse: completed
Result: 1 successful, 0 failed
Output: disease.json plus Info, Life/DD/TPD, IP, Health
```

## 1. Goal

Support imported names that resolve to a disease category/menu instead of a
single disease-detail page. The crawler must expand the category, recursively
inspect its child menu entries, and send only confirmed disease-detail pages
through the existing fetch, clean, parse, and report pipeline.

Primary live acceptance case:

```text
Cardiac arrhythmia (imported query)
  -> Cardiac arrhythmias (website category)
      -> Atrial fibrillation
      -> Brugada syndrome / Brugada pattern ECG
      -> Ectopic beats
      -> Paroxysmal supraventricular tachycardia
      -> Sinus arrhythmia
      -> Ventricular fibrillation
      -> Ventricular tachycardia
```

The live category is currently classified as `disease_list` with confidence
`0.83`. It has no disease content of its own. All seven direct children were
classified as `disease_detail` with confidence `1.00`.

## 2. Scope

In scope:

- imported-name mode;
- exact search-result matching;
- narrowly constrained English singular/plural category matching;
- `disease_list` detection and direct-child extraction;
- recursive breadth-first category traversal;
- canonical-URL deduplication and cycle prevention;
- parent-child provenance;
- detailed search/category audit;
- progress and grouped result presentation;
- deterministic and live tests.

Out of scope for this change:

- fuzzy semantic matching of unrelated names;
- automatically crawling the entire Medical tree without limits;
- clicking `+`, `Edit`, or `Edit note`;
- changing the existing four-tab and related-detail extraction behavior;
- treating a category page as a disease document.

## 3. Operator experience

Add an option to the `Import tên bệnh` panel:

```text
[x] Mở rộng menu bệnh cha
```

Default: enabled.

Advanced limits:

- maximum category depth: default `5`, allowed `1..8`;
- maximum expanded nodes per job: default `100`, allowed `1..250`;
- maximum confirmed child diseases: default `100`, allowed `1..250`.

Before execution, the UI shows:

- imported root-name count;
- category expansion enabled/disabled;
- maximum possible child-disease output.

During discovery, progress messages distinguish:

- imported roots processed;
- categories expanded;
- queued nodes;
- confirmed disease details;
- skipped/failed nodes.

The final report groups results by imported root and menu path. Category pages
appear as grouping/provenance nodes, not disease items.

## 4. API contract

Extend `RunRequest` with backward-compatible defaults:

```json
{
  "discovery_mode": "import",
  "disease_names": ["Cardiac arrhythmia"],
  "expand_disease_categories": true,
  "category_max_depth": 5,
  "category_max_nodes": 100,
  "category_max_diseases": 100
}
```

Validation:

- category options are used only in import mode;
- all limits must remain inside backend hard limits;
- imported root names remain limited to 25;
- expanded child count is separate from imported root count;
- disabling expansion preserves the current exact-detail behavior.

## 5. Safe search-name matching

Apply matching strategies in this order:

1. `exact_normalized`
   - case-insensitive;
   - punctuation-insensitive;
   - collapsed whitespace;
   - same-domain URL required.
2. `singular_plural_category`
   - used only when exact matching returns no candidate;
   - only one candidate may remain;
   - token sequences must be identical except for a constrained final-token
     English plural transformation such as `s`, `es`, or `y -> ies`;
   - the candidate must subsequently classify as `disease_list`;
   - every decision is written to the import audit.
3. No other approximate result is selected.

Example:

```text
Cardiac arrhythmia -> Cardiac arrhythmias
```

If multiple plural candidates exist, record
`ambiguous_singular_plural_results` and do not choose automatically.

## 6. Traversal algorithm

Use bounded breadth-first search because it preserves category grouping and
prevents a deep branch from starving sibling diseases.

```text
for each imported root query
  search through #searchTerm
  select safe candidate
  enqueue root node at depth 0

while queue is not empty
  dequeue node
  canonicalize URL
  skip if already visited
  stop/record if node or depth limit is reached
  navigate using allowlisted GET
  classify page

  if disease_detail
    wait for stable content
    classify a second time
    enqueue DiscoveredItem only if still disease_detail

  if disease_list
    locate active link in #sidemenutree
    extract direct child links only
    enqueue each child with depth + 1 and parent provenance

  otherwise
    record classification and skip reason
```

Direct children must be selected from the active menu item's immediate child
list. Do not collect unrelated sibling branches or every descendant from the
whole sidebar in one step.

## 7. Safety and loop controls

Required guards:

- HTTPS and Genre Manuals domain allowlist;
- canonical URL visited set shared across imported roots;
- no form submission other than the read-only site search GET;
- no `+`, `Edit`, `Edit note`, cart, or mutation action;
- `category_max_depth`;
- `category_max_nodes`;
- `category_max_diseases`;
- existing navigation timeout and session-expiry handling;
- repeated-fingerprint/no-progress detection;
- deterministic queue ordering by menu order, then canonical URL;
- graceful partial completion when a category limit is reached.

Fatal conditions:

- invalid/expired authentication;
- CAPTCHA/MFA requiring operator action;
- navigation leaving the domain allowlist;
- storage failure for audit/provenance.

Per-node nonfatal conditions:

- unknown page type;
- empty category;
- child content not stable;
- child URL already visited;
- depth/node/disease limit reached;
- candidate rejected by detector.

## 8. Data and provenance

Add a category-discovery node contract:

```json
{
  "root_query": "Cardiac arrhythmia",
  "label": "Atrial fibrillation",
  "url": "https://www.genre-manuals.com/en_atrial_fibrillation.htm",
  "canonical_url": "https://www.genre-manuals.com/en_atrial_fibrillation.htm",
  "parent_url": "https://www.genre-manuals.com/en_cardiac_arrhythmias.htm",
  "menu_path": ["Cardiac arrhythmias", "Atrial fibrillation"],
  "depth": 1,
  "page_type": "disease_detail",
  "confidence": 1.0,
  "status": "confirmed",
  "reason_code": "disease_detail_confirmed"
}
```

Persistence design:

- keep `crawl_items` restricted to confirmed disease details;
- add a migration-backed provenance table keyed by
  `(job_id, item_id, root_query, menu_path)`;
- persist all category/detail/skip nodes in
  `category-expansion.json`;
- extend `import-search.json` with selected match strategy and root-category
  expansion summary;
- expose both artifacts through the job artifact allowlist;
- add optional provenance to report rows;
- defer a `disease.json` schema bump unless provenance must be embedded in
  every disease document.

Deduplicated diseases may belong to multiple imported roots. Store all
provenance paths while fetching/parsing the canonical disease only once.

## 9. Reason codes

Search:

- `exact_title_not_found`
- `singular_plural_category_match`
- `ambiguous_singular_plural_results`
- `search_navigation_timeout`
- `search_input_not_found`

Category:

- `category_confirmed`
- `category_empty`
- `category_child_enqueued`
- `category_depth_limit`
- `category_node_limit`
- `category_disease_limit`
- `duplicate_canonical_url`

Child validation:

- `disease_detail_confirmed`
- `candidate_not_disease_detail`
- `candidate_not_stable_disease_detail`
- `page_type_unknown`
- `content_not_ready`

Each code must have a human-readable Vietnamese reason and ordered action
steps in the audit artifact.

## 10. Implementation phases

### Phase A — Contracts and configuration

- extend `RunRequest`;
- add category-node/provenance models;
- add configuration hard limits;
- define reason-code constants;
- add database migration for multi-path provenance.

Exit criteria:

- request validation and model round-trip tests pass;
- automatic mode and import-detail mode remain backward compatible.

### Phase B — Search matcher

- retain exact matching as the first strategy;
- add isolated singular/plural candidate analysis;
- require a unique candidate;
- defer final acceptance until page classification;
- extend import audit with `match_strategy`.

Exit criteria:

- `Cardiac arrhythmia` may select `Cardiac arrhythmias` only as a category;
- unrelated approximate results remain rejected.

### Phase C — Category traversal service

- add a dedicated bounded BFS service;
- extract only direct child menu links;
- classify category/detail/unknown nodes;
- apply limits, visited URLs, and stable-detail confirmation;
- upsert confirmed child diseases;
- persist provenance and `category-expansion.json`.

Exit criteria:

- a category is never inserted as a crawl item;
- one canonical disease is fetched once even when reached through two paths.

### Phase D — Pipeline and reporting

- route imported candidates through the expansion service before batch fetch;
- keep fetch, clean, parse, and report services unchanged where possible;
- attach provenance to report rows;
- include category warnings and partial-limit status;
- make category artifact downloadable.

Exit criteria:

- confirmed children use the existing four-tab and related-detail pipeline;
- per-child failures do not stop valid siblings.

### Phase E — Operator UI

- add category expansion toggle and limits;
- show live category/node/disease counters;
- group report rows by imported root and menu path;
- add `Nhật ký menu cha-con` artifact link;
- clearly label partial results caused by limits.

Exit criteria:

- operator can distinguish imported roots, category pages, confirmed diseases,
  and skipped nodes without opening raw JSON.

### Phase F — Tests and live rollout

- unit tests for inflection matching, direct-child extraction, queue order,
  deduplication, limits, reason codes, and provenance;
- integration tests for multi-level categories and shared children;
- regression tests for ordinary imported disease details;
- browser UI tests for toggle, limits, progress, grouping, and artifact links;
- live canary on `Cardiac arrhythmia`;
- negative canary with a nonexistent and an ambiguous name.

Exit criteria:

- lint, type-check, and full automated suite pass;
- live canary meets every acceptance criterion below.

## 11. Acceptance criteria

For imported query `Cardiac arrhythmia`:

1. Search audit records the singular/plural category strategy.
2. `Cardiac arrhythmias` is classified as `disease_list`, not parsed as a
   disease.
3. Exactly seven direct children are discovered.
4. All seven children are independently classified.
5. Seven confirmed disease details enter the existing content pipeline.
6. No unrelated Medical branch is added.
7. No canonical URL is fetched twice.
8. Every result contains root, parent, path, and depth provenance.
9. Four source tabs and read-only related details are captured per supported
   child page.
10. `+`, `Edit`, and `Edit note` remain untouched.
11. Category and import audit artifacts are downloadable from the UI.
12. A failed child does not block successful siblings.

## 12. Rollback and compatibility

- feature is gated by `expand_disease_categories`;
- disabling it restores the current import behavior;
- no change to automatic discovery when the flag is off;
- existing reports and disease JSON remain readable;
- the database migration is additive;
- category artifacts are optional for old jobs;
- canary initially uses one imported root and conservative limits before
  enabling the option by default.

## 13. Recommended implementation order

Implement Phase A through F sequentially. Do not begin UI grouping before the
category-node and provenance contracts are stable. Do not enable
singular/plural matching without the unique-result and post-navigation
`disease_list` safeguards.
