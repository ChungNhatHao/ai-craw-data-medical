# 06 — Testing, Observability and Security

## 1. Test pyramid

### Unit tests

Không cần network/browser:

- URL canonicalization và domain allowlist.
- Slug/item ID.
- HTML cleaning.
- Markdown normalization.
- Content/schema hashing.
- Disease schema validation.
- Retry classification/backoff.
- State transition hợp lệ/không hợp lệ.
- Report aggregation.
- Prompt response parsing.

### Fixture/integration tests

Dùng HTML và screenshot fixture:

- Login thành công/thất bại/session expired.
- Disease list một trang/nhiều trang.
- Duplicate link.
- Detail đầy đủ/thiếu section/table.
- Popup che content.
- DOM layout cũ/mới.
- Empty/blocked/CAPTCHA page.
- Invalid structured model output.
- Crash recovery sau từng checkpoint.

### E2E smoke

Trên staging/site thật đã được phép:

1. Validate/login.
2. Discover giới hạn 1 page.
3. Crawl 1–3 item.
4. Kiểm tra artifact/schema/report.
5. Resume một job bị dừng có chủ ý.

Không chạy full crawl trong CI.

## 2. Test doubles

- Fake site plugin cho graph test.
- Local HTTP fixture server cho navigation test.
- Fake model trả JSON xác định.
- Fake clock/random cho backoff test.
- Temporary SQLite và artifact directory cho integration.
- Vision response fixture; CI không gọi Vision thật theo mặc định.

## 3. Quality gates

Trước merge:

- Formatter/linter/type check pass.
- Unit và integration tests pass.
- Không có secret trong diff/fixture.
- Migration chạy trên DB mới và DB version trước.
- Public model có schema test.
- Plugin selector thay đổi có fixture tương ứng.

Coverage ưu tiên branch quan trọng hơn con số tổng. Mục tiêu đề xuất: core,
storage, parser, state transition đạt tối thiểu 80%; browser E2E đánh giá bằng
scenario coverage.

## 4. Acceptance scenarios

| Scenario | Kỳ vọng |
|---|---|
| Cookie hợp lệ | không login lại |
| Cookie hết hạn | login lại một lần |
| Restart sau raw write | resume từ raw, không fetch lại |
| Content không đổi | không gọi LLM |
| LLM JSON sai lần đầu | repair một lần rồi validate |
| Một item fail | job tiếp tục item khác |
| Nhiều lỗi block | job pause |
| Duplicate URL | chỉ một item/job |
| Duplicate content | giữ provenance và `duplicate_of` |
| Cancel | checkpoint, đóng browser, state terminal |
| Current page là disease detail | classifier xác nhận rồi mới crawl |
| Current page là list/home | tìm candidate và lặp navigation |
| Current page là login | refresh session rồi quay lại flow |
| Repeated page fingerprint | dừng ở loop guard, lưu evidence |
| Unknown page đến max hops | `NAVIGATION_LOOP_EXHAUSTED`, không loop vô hạn |

## 5. Structured logging

Mỗi event dùng JSON fields:

```text
timestamp
level
event
request_id
job_id
item_id
plugin
stage
attempt
url_host
duration_ms
error_code
```

Không log full query khi có token, request/response header, cookie, password,
full LLM prompt chứa dữ liệu nhạy cảm hoặc HTML quá lớn.

Log rotation theo size/time; retention cấu hình.

## 6. Metrics/report

Metrics cấp job:

- discovered/completed/unchanged/failed.
- item throughput và duration p50/p95.
- retry theo error code.
- login/session refresh count.
- LLM/Vision call count, token, duration.
- raw/processed bytes.
- parse warning count.

`report.json`:

```json
{
  "job_id": "uuid",
  "status": "completed_with_errors",
  "counts": {
    "discovered": 100,
    "completed": 93,
    "unchanged": 4,
    "failed": 3
  },
  "errors_by_code": {"CONTENT_EMPTY": 2, "NETWORK_TIMEOUT": 1},
  "llm": {"calls": 93, "vision_calls": 1},
  "limits_reached": [],
  "started_at": "...",
  "finished_at": "..."
}
```

## 7. Screenshot/evidence

Chụp:

- Detail page sau content ready.
- Error page khi navigation/selector/content fail.
- Trước/sau Vision action nếu được kích hoạt.

Không chụp:

- Password đang hiển thị.
- Cookie/devtools/storage state.
- Trang account/profile không thuộc crawl scope.

Screenshot lỗi có retention và access control tương đương raw HTML.

## 8. Security checklist

- `.env`, session file, SQLite production và output nhạy cảm nằm ngoài Git.
- File path được tạo từ safe slug + hash; chống path traversal.
- URL bị giới hạn scheme `https/http` và allowed domain; chống SSRF/open redirect.
- Redirect sau navigation được validate lại.
- HTML không được render trực tiếp trong admin UI nếu chưa sanitize.
- LLM output là untrusted input và phải validate.
- Plugin/action allowlist ngăn model tự do thao tác browser.
- Dependency pinning và vulnerability scan trong CI.
- Container non-root, filesystem quyền tối thiểu.
- API production có authentication/authorization trước khi expose.

## 9. Medical data integrity

- Mỗi assertion phải giữ liên kết nguồn.
- Không sửa câu chữ làm mất negation như “không”, “chưa chứng minh”.
- Không tự chuyển đơn vị/liều lượng nếu không có rule được test.
- Lưu raw/Markdown để reviewer đối chiếu.
- Schema warning khi section bị cắt, table không parse hoặc confidence thấp.
- Output phải có disclaimer nội bộ: dữ liệu được trích xuất tự động, cần review
  trước khi dùng cho quyết định y khoa.

## 10. Compliance gate

Trước production:

- Owner xác nhận Terms of Service, robots/access policy và quyền sử dụng nội dung.
- Xác nhận account automation được phép.
- Xác định dữ liệu có thông tin cá nhân hay không.
- Chốt retention và quyền truy cập artifact.
- Chốt request rate/concurrency có trách nhiệm.

CAPTCHA hoặc block là tín hiệu dừng và yêu cầu operator, không phải vấn đề cần
“vượt qua”.
