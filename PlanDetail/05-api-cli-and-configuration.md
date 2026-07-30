# 05 — API, CLI and Configuration

## 1. API contract

Prefix đề xuất: `/api/v1`.

| Method | Endpoint | Chức năng |
|---|---|---|
| GET | `/health/live` | process đang sống |
| GET | `/health/ready` | DB/config/browser dependency sẵn sàng |
| GET | `/plugins` | danh sách plugin và capability |
| POST | `/sessions/{plugin}/validate` | kiểm tra session |
| POST | `/sessions/{plugin}/login` | tạo session được kiểm soát |
| POST | `/jobs` | tạo job |
| GET | `/jobs` | list/filter job |
| GET | `/jobs/{id}` | progress và summary |
| POST | `/jobs/{id}/pause` | yêu cầu pause |
| POST | `/jobs/{id}/resume` | resume |
| POST | `/jobs/{id}/cancel` | cancel |
| POST | `/jobs/{id}/retry-failed` | retry queue |
| GET | `/jobs/{id}/report` | report |
| POST | `/jobs/{id}/export` | tạo export snapshot |

### Tạo job

```json
{
  "plugin": "genre_manuals",
  "mode": "full",
  "limits": {
    "max_items": 100,
    "max_pages": 20
  },
  "capture_screenshot": true
}
```

Response `202 Accepted`:

```json
{
  "job_id": "uuid",
  "status": "created",
  "status_url": "/api/v1/jobs/uuid"
}
```

API không nhận raw password trong job payload. Login endpoint chỉ được bật trong
môi trường phù hợp; ưu tiên credential từ secret config.

## 2. API error shape

```json
{
  "error": {
    "code": "JOB_NOT_RESUMABLE",
    "message": "Job is already completed",
    "request_id": "uuid",
    "details": {}
  }
}
```

Không trả stack trace, credential, cookie hoặc filesystem path nội bộ.

## 3. Job execution

MVP có thể dùng một in-process worker queue với các giới hạn:

- API startup recover job `running` thành `paused/recoverable`.
- Chỉ một worker crawl mặc định.
- Job state luôn nằm trong SQLite, không chỉ memory.
- Shutdown đợi checkpoint hiện tại.

Nếu cần multi-process/distributed worker sau V2, tách interface queue; chưa đưa
Redis/Celery vào khi chưa có nhu cầu.

## 4. CLI

```text
crawl plugins
crawl session validate --plugin genre_manuals
crawl login --plugin genre_manuals
crawl discover --plugin genre_manuals --max-pages 2
crawl run --plugin genre_manuals --mode full --max-items 10
crawl status --job-id UUID
crawl pause --job-id UUID
crawl resume --job-id UUID
crawl retry-failed --job-id UUID --error-code NETWORK_TIMEOUT
crawl export --job-id UUID --format json
```

Exit code:

| Code | Ý nghĩa |
|---:|---|
| 0 | thành công |
| 1 | lỗi runtime/job |
| 2 | CLI/config không hợp lệ |
| 3 | auth/session cần operator |
| 4 | job hoàn tất nhưng có item lỗi |

CLI output người đọc được theo mặc định; `--json` trả machine-readable output.

## 5. Configuration

Nhóm config:

```text
APP_ENV
LOG_LEVEL
DATABASE_PATH
OUTPUT_ROOT
SESSION_ROOT
BROWSER_HEADLESS
BROWSER_NAVIGATION_TIMEOUT_MS
BROWSER_SELECTOR_TIMEOUT_MS
CRAWL_DELAY_MIN_MS
CRAWL_DELAY_MAX_MS
CRAWL_MAX_ITEMS
CRAWL_MAX_PAGES
CRAWL_MAX_RETRIES
LLM_MODEL
LLM_REQUEST_TIMEOUT_SECONDS
LLM_MAX_CALLS_PER_JOB
VISION_ENABLED
VISION_CONFIDENCE_THRESHOLD
VISION_MAX_CALLS_PER_ITEM
GENRE_MANUALS_USERNAME
GENRE_MANUALS_PASSWORD
```

Quy tắc:

- Pydantic Settings validate startup.
- Production fail-fast nếu secret/config bắt buộc thiếu.
- Relative path resolve từ app data root rõ ràng.
- Job lưu config snapshot đã redact.
- Config precedence: CLI/job override → environment → defaults.
- Credential không được phép override qua public job API.

## 6. Prompt/model configuration

Mỗi model call lưu:

- Provider/model identifier thực tế.
- Prompt name/version.
- Schema version.
- Token usage, duration, retry count.
- Không lưu secret.

Tên model không hard-code xuyên codebase; dùng capability config:

```python
class ModelConfig:
    text_model: str
    vision_model: str
    supports_structured_output: bool
```

Startup validation phải phát hiện model không hỗ trợ structured output/Vision.

## 7. Docker

Container:

- Base image Python 3.12 + Playwright browser/dependencies.
- Chạy non-root.
- Mount riêng `output/`, `state/`, `logs/`.
- Secret inject qua environment/secret mount.
- Healthcheck gọi readiness endpoint.
- Pin Python dependency và browser version.

`docker-compose.yml` tối thiểu một service crawler. SQLite phù hợp một instance;
không scale nhiều replica cùng ghi một DB file.

## 8. Export

Export snapshot chỉ lấy item `completed` hoặc tùy chọn include failed manifest:

```text
exports/{job_id}/{timestamp}/
├── diseases.jsonl
├── disease-list.json
├── report.json
└── checksums.sha256
```

JSONL thích hợp dữ liệu lớn và stream. `disease-list.json` chứa ID, name, URL,
status, content hash; không duplicate toàn bộ document.

Để tương thích deliverable của plan gốc, exporter hỗ trợ thêm layout:

```text
output/compat/
├── disease-list.json
└── Diseases/
    └── {slug}--{item_id_12}/
        ├── raw.html
        ├── markdown.md
        ├── disease.json
        └── screenshot.png
```

Đây là export view từ artifact store, không phải nơi lưu state chính. Nhờ vậy
layout dễ dùng vẫn được giữ mà resume/versioning không phụ thuộc tên bệnh.
