# Oracle output database

The DDL in `oracle_output_schema.sql` targets Oracle Database 19c and newer.
It stores both crawler execution state and the complete generated output.

See `ORACLE_OUTPUT_ERD.md` for the entity relationship diagram and the full
parent/child relationship matrix.

## Storage model

- `crawl_jobs`, `crawl_items`: run and item lifecycle.
- `disease_documents`: the complete `disease.json` as a lossless JSON CLOB,
  plus frequently queried scalar columns.
- `disease_field_values`, `disease_sections`, `disease_menu_nodes`: normalized
  disease content and breadcrumb hierarchy.
- `disease_tabs`, `tab_tables`, `tab_related_details`: Info, Life/DD/TPD, IP,
  and Health content.
- `classifications`, `classification_ratings`: queryable classification tree,
  levels, parents, paths, codes, and rating values.
- `item_coverage`, `coverage_checks`, `coverage_messages`: coverage result and
  reasons.
- `output_artifacts`: every text or binary artifact, including raw HTML,
  screenshots, job reports, site profiles, and coverage reports.

## Important choices

`disease_documents.document_json` remains the source of truth. Normalized rows
are projections used for SQL reporting. Both must be written in one database
transaction so a partial import cannot become visible.

Oracle 19c does not have a SQL Boolean type, so Boolean values use `NUMBER(1)`
with checks. JSON uses `CLOB` with `IS JSON` constraints. On Oracle 21c or 23ai,
these JSON CLOB columns can use the native `JSON` type.

URLs are stored as full text, while `canonical_url_hash` is indexed to avoid
Oracle index-size problems with 2,048-character URLs. The application should
store the lowercase SHA-256 digest of the canonical URL in that column.

The application currently uses SQLite repositories and filesystem artifacts.
This DDL defines the Oracle target schema; switching runtime persistence also
requires an Oracle repository/ingestion adapter and a one-time artifact import.
