# 02 — Data and Storage

## 1. Các model cốt lõi

### Crawl job

```python
class CrawlJob(BaseModel):
    id: UUID
    plugin: str
    status: Literal[
        "created", "running", "pausing", "paused",
        "completed", "completed_with_errors", "failed", "cancelled"
    ]
    mode: Literal["full", "incremental", "retry_failed"]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    config_snapshot: dict
```

### Crawl item

```python
class CrawlItem(BaseModel):
    id: str                 # sha256(canonical_url)
    job_id: UUID
    source_url: HttpUrl
    canonical_url: HttpUrl
    title_hint: str | None
    status: Literal[
        "discovered", "fetching", "fetched", "cleaning", "cleaned",
        "parsing", "parsed", "completed", "retryable_failed",
        "permanent_failed", "skipped_unchanged", "cancelled"
    ]
    attempt_count: int
    content_hash: str | None
    previous_content_hash: str | None
    last_error_code: str | None
```

### Disease document

Schema v1:

```json
{
  "schema_version": "1.0",
  "document_id": "sha256 canonical URL",
  "source": {
    "plugin": "genre_manuals",
    "url": "https://example/detail",
    "canonical_url": "https://example/detail",
    "retrieved_at": "2026-07-28T10:00:00Z",
    "content_hash": "sha256:...",
    "language": "en"
  },
  "disease": {
    "name": "Required string",
    "aliases": [],
    "summary": null,
    "causes": [],
    "risk_factors": [],
    "symptoms": [],
    "diagnosis": [],
    "treatment": [],
    "prevention": [],
    "prognosis": null,
    "when_to_seek_care": []
  },
  "sections": [
    {
      "heading": "Overview",
      "level": 2,
      "order": 1,
      "markdown": "..."
    }
  ],
  "parse_metadata": {
    "method": "rules|llm|rules+llm",
    "model": null,
    "prompt_version": null,
    "parser_version": "1.0.0",
    "confidence": null,
    "warnings": []
  }
}
```

Quy tắc:

- `disease.name`, source URL và retrieval time là bắt buộc.
- Nội dung không có trong nguồn dùng `null`/`[]`.
- `sections` giữ nội dung ít mất mát hơn các field y khoa chuẩn hóa.
- Không ghi chain-of-thought hoặc response thô của model vào public JSON.
- Lưu `schema_version`, `parser_version`, `prompt_version` độc lập.

## 2. SQLite schema

### `crawl_jobs`

| Cột | Kiểu | Ghi chú |
|---|---|---|
| id | TEXT PK | UUID |
| plugin | TEXT | indexed |
| status | TEXT | indexed |
| mode | TEXT | |
| config_json | TEXT | config snapshot đã redact |
| created_at | TEXT | UTC ISO-8601 |
| started_at | TEXT nullable | |
| finished_at | TEXT nullable | |
| cancel_requested | INTEGER | 0/1 |

### `crawl_items`

| Cột | Kiểu | Ghi chú |
|---|---|---|
| job_id | TEXT | composite PK |
| item_id | TEXT | composite PK |
| source_url | TEXT | |
| canonical_url | TEXT | indexed |
| title_hint | TEXT nullable | |
| status | TEXT | indexed |
| attempt_count | INTEGER | |
| content_hash | TEXT nullable | |
| previous_content_hash | TEXT nullable | |
| last_error_code | TEXT nullable | |
| artifact_dir | TEXT nullable | relative path |
| updated_at | TEXT | |

### `crawl_attempts`

| Cột | Kiểu | Ghi chú |
|---|---|---|
| id | INTEGER PK | autoincrement |
| job_id/item_id | TEXT | indexed |
| attempt_no | INTEGER | |
| stage | TEXT | |
| started_at/finished_at | TEXT | |
| result | TEXT | success/failure |
| error_code | TEXT nullable | |
| error_message | TEXT nullable | sanitized |
| details_json | TEXT | không chứa secret |

### `document_versions`

Lưu lịch sử `canonical_url`, `content_hash`, `schema_hash`, artifact path,
retrieval time và job tạo ra version. Bảng này là nguồn để incremental crawl
so sánh với version gần nhất.

## 3. Layout artifact

```text
output/
└── jobs/
    └── {job_id}/
        ├── job.json
        ├── disease-list.json
        ├── report.json
        └── items/
            └── {slug}--{item_id_12}/
                ├── manifest.json
                ├── raw.html
                ├── content.html
                ├── markdown.md
                ├── disease.json
                ├── screenshot.png
                └── error.json
```

`slug` chỉ để con người đọc; `item_id_12` đảm bảo uniqueness. Không dùng disease
name làm ID vì có thể trùng, đổi tên hoặc chứa ký tự không hợp lệ.

## 4. Manifest

`manifest.json` ghi:

- job ID, item ID, plugin, URL.
- state hiện tại và timestamp từng stage.
- tên, size, SHA-256 của từng artifact.
- HTTP/status/navigation metadata an toàn.
- content/schema hash.
- parser, prompt, model version.
- warning và error gần nhất.

Manifest chỉ được cập nhật sau khi artifact tương ứng đã ghi và validate.

## 5. Atomic write

Quy trình:

1. Tạo file cùng thư mục với suffix `.tmp`.
2. Flush và đóng file.
3. Parse/validate file nếu là JSON.
4. Rename atomically thành tên cuối.
5. Update manifest.
6. Commit database state.

Nếu crash giữa bước 4 và 6, recovery kiểm tra artifact hợp lệ rồi đưa DB tiến
lên state phù hợp. Không ghi đè version tốt nếu output mới chưa validate.

## 6. Canonical URL và ID

Canonicalization:

- Lowercase scheme và host.
- Xóa fragment.
- Xóa tracking params đã allowlist như `utm_*`.
- Sort query params có ý nghĩa.
- Chuẩn hóa trailing slash theo plugin.
- Ưu tiên `<link rel="canonical">` nếu cùng allowed domain và hợp lệ.

```text
item_id = sha256(plugin_name + "\n" + canonical_url)
```

Không follow URL ngoài allowed domain khi discovery.

## 7. Hash và duplicate

### `raw_hash`

SHA-256 bytes của HTML gốc; dùng audit, không dùng quyết định unchanged vì HTML
có thể chứa nonce/timestamp.

### `content_hash`

SHA-256 của Markdown sau:

- Unicode NFC.
- Chuẩn hóa line ending và whitespace.
- Xóa các block boilerplate được plugin xác định.
- Chuẩn hóa link tracking.
- Không lowercase nội dung và không thay đổi thứ tự section.

### `schema_hash`

Hash JSON canonical đã bỏ `retrieved_at`, parse metadata và warning.

Decision:

| So sánh | Hành động |
|---|---|
| content hash không đổi | `skipped_unchanged`, không gọi LLM |
| content đổi | parse và tạo document version mới |
| URL mới, hash trùng URL khác | ghi `duplicate_of`, vẫn giữ provenance |
| hash thiếu/hỏng | xử lý lại từ artifact gần nhất |

## 8. Retention

Mặc định giữ raw HTML và JSON của mọi version trong giai đoạn MVP/V2. Trước
production cần chốt retention theo dung lượng và quyền nội dung. Cleanup chỉ
được triển khai khi có policy rõ ràng; không tự động xóa evidence.
