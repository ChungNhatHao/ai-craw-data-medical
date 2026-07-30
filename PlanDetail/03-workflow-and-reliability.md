# 03 — Workflow and Reliability

## 1. LangGraph state

```python
class AgentState(TypedDict):
    job_id: str
    plugin_name: str
    mode: str
    current_item_id: str | None
    current_url: str | None
    current_page_type: str | None
    navigation_hop_count: int
    no_progress_count: int
    visited_page_fingerprints: list[str]
    session_valid: bool
    stage: str
    attempt_no: int
    artifact_refs: dict[str, str]
    last_error: dict | None
    recovery_action: str | None
    stop_requested: bool
```

Danh sách pending/completed không đưa hết vào graph state vì có thể rất lớn;
repository là source of truth. Graph chỉ giữ current item và reference.

## 2. Graph cấp job

```text
initialize_job
  → acquire_browser
  → validate_session
  ├─ invalid → login → validate_session
  └─ valid
  → discover_items
  → select_next_item
  ├─ has item → navigate_and_confirm_detail
  │              ├─ confirmed → run_item_subgraph → checkpoint → select_next_item
  │              └─ not detail → navigation_detection_loop
  └─ empty → build_report → finalize_job → release_browser
```

Browser luôn được release trong cleanup/finally kể cả job fail hoặc cancel.

## 3. Navigation detection loop

Crawler không được giả định rằng click/navigation thành công đồng nghĩa đã đến
trang nội dung bệnh. Sau mỗi navigation, node `classify_current_page` phải trả
một trong các loại:

```text
DISEASE_DETAIL
DISEASE_LIST
HOME_OR_MENU
LOGIN
BLOCKED_OR_CAPTCHA
UNKNOWN
```

Flow:

```text
open candidate/current page
  → dismiss_known_popups
  → classify_current_page
      ├─ DISEASE_DETAIL → confirm content markers → fetch/crawl
      ├─ DISEASE_LIST   → select unvisited disease candidate ─┐
      ├─ HOME_OR_MENU   → find disease menu/search action ───┤
      ├─ LOGIN          → login → return to last safe URL ───┤
      ├─ UNKNOWN        → deterministic recovery/Vision ─────┤
      └─ BLOCKED        → pause job for operator              │
                                                             │
                     ◀──────── navigate and classify again ──┘
```

Chỉ nhánh `DISEASE_DETAIL` được phép chuyển sang `persist_raw` và parse.

### Page classifier

Classifier deterministic chấm điểm từ nhiều tín hiệu, không dựa vào một
selector duy nhất:

- URL pattern và canonical URL.
- Breadcrumb/menu state.
- Heading/title của bệnh.
- Content root và minimum text length.
- Các section marker y khoa như overview, symptoms, diagnosis, treatment.
- Link density: list page thường có nhiều link, ít nội dung dài.
- Login form, CAPTCHA/block marker.
- Negative marker: search result, menu, landing page, error page.

Kết quả gồm `page_type`, `confidence`, `matched_signals` và `fingerprint`.
Trang chỉ được xác nhận là `DISEASE_DETAIL` khi đạt ngưỡng cấu hình và có cả
content root lẫn disease heading. Trường hợp mơ hồ là `UNKNOWN`, không được crawl.

### Loop guard

Mặc định đề xuất:

- `max_navigation_hops_per_item = 12`.
- Cùng page fingerprint xuất hiện 3 lần: coi là stuck.
- 2 vòng liên tiếp không có URL/candidate/DOM state mới: `no_progress`.
- Candidate đã visited không được click lại trong cùng item attempt.
- Hết giới hạn: lỗi `NAVIGATION_LOOP_EXHAUSTED`, lưu screenshot/trace và đưa
  item vào failed queue.

Fingerprint lấy từ canonical URL + page type + heading + hash vùng navigation;
không dùng screenshot hash làm tín hiệu duy nhất.

## 4. Subgraph cấp item

```text
prepare_item
 → navigate_and_confirm_detail
 → fetch
 → persist_raw
 → extract_main_content
 → convert_markdown
 → compare_hash
 ├─ unchanged → mark_unchanged
 └─ changed
     → parse_structured
     → validate_schema
     ├─ valid → persist_document → complete
     └─ invalid → repair_once → validate_schema
                    ├─ valid → persist_document → complete
                    └─ invalid → classify_failure
```

Mỗi node:

- Nhận state + service dependency.
- Có timeout riêng.
- Ghi attempt/stage duration.
- Không swallow exception.
- Chuyển exception thành error code chuẩn ở một boundary duy nhất.

## 5. Error taxonomy

| Code | Retry | Xử lý |
|---|---:|---|
| `AUTH_INVALID_CREDENTIALS` | không | fail job, yêu cầu operator |
| `AUTH_SESSION_EXPIRED` | 1 | login lại rồi retry item |
| `NETWORK_TIMEOUT` | 3 | backoff |
| `NETWORK_DNS` | 3 | backoff |
| `HTTP_RATE_LIMITED` | theo policy | dùng Retry-After |
| `HTTP_SERVER_ERROR` | 3 | backoff |
| `NAVIGATION_FAILED` | 2 | reload/new page |
| `PAGE_TYPE_UNKNOWN` | loop policy | tìm candidate/recovery action khác |
| `NAVIGATION_LOOP_EXHAUSTED` | không trong attempt hiện tại | failed queue + evidence |
| `SELECTOR_NOT_FOUND` | fallback | selector → heuristic → Vision |
| `POPUP_BLOCKING` | 2 | close known popup |
| `CONTENT_EMPTY` | 2 | wait/reload rồi fail |
| `CONTENT_INVALID` | 1 | alternate extractor |
| `LLM_TIMEOUT` | 2 | retry request |
| `LLM_OUTPUT_INVALID` | 1 | repair structured output |
| `SCHEMA_VALIDATION` | 1 | repair, sau đó permanent |
| `STORAGE_WRITE` | 2 | retry atomic write |
| `CAPTCHA_OR_BLOCKED` | không | pause job/operator action |
| `UNEXPECTED` | 1 | capture evidence, failed queue |

Thông báo lỗi phải sanitize credential, cookie, request header và model key.

## 6. Retry policy

Backoff mặc định:

```text
delay = min(base * 2^(attempt-1) + random_jitter, max_delay)
base = 2 seconds
max_delay = 60 seconds
```

- Retry count tính theo stage, không phải toàn job.
- Mỗi retry tạo `crawl_attempts` record mới.
- Không retry validation vô hạn.
- `Retry-After` có ưu tiên hơn công thức.
- Circuit breaker tạm dừng job nếu có nhiều lỗi auth/block/rate-limit liên tiếp.

Ngưỡng đề xuất:

- 3 lỗi auth/session liên tiếp: pause job.
- 5 item liên tiếp `CAPTCHA_OR_BLOCKED`: pause job.
- Error rate > 50% sau ít nhất 10 item: pause để operator kiểm tra.

## 7. Checkpoint và resume

Checkpoint database sau các mốc:

1. Item discovered.
2. Raw artifact persisted.
3. Markdown persisted.
4. Structured JSON validated.
5. Item completed/failed.

Recovery khi process restart:

| DB state | Artifact | Hành động |
|---|---|---|
| `fetching` | raw hợp lệ | chuyển `fetched` |
| `fetching` | không raw | chuyển `discovered` |
| `cleaning` | markdown hợp lệ | chuyển `cleaned` |
| `parsing` | disease JSON hợp lệ | chuyển `parsed` |
| `parsed` | JSON hợp lệ | finalize item |
| `completed` | artifact thiếu | đánh dấu integrity error |

Resume không reset attempt count hoặc xóa lịch sử lỗi.

## 8. Idempotency

- `create job` hỗ trợ optional idempotency key.
- Discover dùng upsert `(job_id, item_id)`.
- Persist artifact cùng content hash không tạo version mới.
- Finalize completed item là no-op khi gọi lại.
- Retry failed tạo attempt mới nhưng giữ item ID.
- Export có thể chạy nhiều lần và cho cùng kết quả với cùng snapshot.

## 9. Cancellation và graceful shutdown

- `cancel_requested` được kiểm tra trước mỗi item và trước LLM call.
- Không interrupt giữa atomic file write/DB transaction.
- Item hiện tại hoàn tất checkpoint an toàn rồi chuyển `cancelled` hoặc giữ state
  resumable.
- SIGTERM: ngừng nhận job, checkpoint, đóng page/context/browser, đóng DB.
- API phân biệt `pause` (có thể resume) và `cancel` (terminal).

## 10. Incremental mode

1. Discover danh sách hiện tại.
2. So sánh canonical URL với `document_versions`.
3. Fetch trang để tạo content hash.
4. Nếu unchanged: không parse lại.
5. Nếu changed/new: chạy parse pipeline.
6. URL từng có nhưng không còn discover: report `possibly_removed`; không xóa.

Incremental mode vẫn phải fetch để biết nội dung đổi nếu site không cung cấp
ETag/Last-Modified đáng tin cậy. Khi header đáng tin cậy, có thể dùng conditional
request như tối ưu sau.

## 11. Failed queue

Failed queue là query từ `crawl_items`, không cần message broker trong V2:

```text
status IN (retryable_failed, permanent_failed)
```

Operator có thể retry:

- Tất cả retryable.
- Theo error code.
- Một danh sách item ID.
- Từ stage cụ thể nếu artifact còn hợp lệ.

Không retry automatic item `permanent_failed` nếu chưa có config/code version
mới hoặc operator override.
