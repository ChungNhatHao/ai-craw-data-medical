# 07 — Delivery Roadmap

## 1. Cách thực hiện

Roadmap gồm MVP 9 ngày và V2 7 ngày. Ước lượng giả định một developer chính và
reviewer phản hồi trong ngày. Owner đã xác nhận có tài khoản hợp lệ trên website
thật. Credential chỉ được cấp qua secret/environment khi triển khai. Nếu thiếu
fixture hoặc xác nhận quyền automation/lưu nội dung, lịch website integration
phải dịch tương ứng.

Mỗi ngày kết thúc bằng:

- Code chạy được.
- Automated test liên quan.
- Demo hoặc artifact kiểm chứng.
- Cập nhật decision/risk nếu có thay đổi.

## 2. MVP — 9 ngày

### Day 1 — Foundation

Status: **DONE — 2026-07-28**. Chi tiết kiểm chứng:
[Day1-Implementation-Report.md](Day1-Implementation-Report.md).

Tasks:

- Khởi tạo project, dependency pinning và config.
- FastAPI health endpoints.
- Loguru structured logging.
- SQLite connection/migration đầu tiên.
- Playwright browser manager smoke test.
- LangGraph skeleton với fake plugin.
- Tạo thư mục artifact qua config.

Acceptance:

- App start và readiness pass.
- Fake job đi từ created đến completed.
- Browser mở/đóng không leak process.
- Unit test chạy bằng một command.

### Day 2 — Session and login

Status: **DONE — LIVE VALIDATED 2026-07-28**. Login thật đã tạo Playwright
storage state thành công; lần chạy thứ hai reuse session mà không cần submit
login form. Session file có permission `0600` và nằm trong Git ignore.

Tasks:

- Credentials/settings model.
- Storage state load/save atomic.
- Plugin login/session contract.
- Implement login và session validation cho `genre_manuals`.
- Redaction và login error taxonomy.
- Fixture tests success/expired/invalid credential.

Acceptance:

- Session hợp lệ được reuse.
- Session hết hạn tự login lại.
- `storage_state` tạo thành công và không xuất hiện trong log/Git.
- Sai credential trả error rõ và không retry vô hạn.

### Day 3 — Navigation

Status: **DONE — LIVE VALIDATED 2026-07-28**. Detection loop đã đi từ home qua
Medical/Ratings/category/subgroup đến trang bệnh thật trong 6 hops, dùng 5
candidate duy nhất. Classifier xác nhận disease detail với confidence `1.0`;
loop guards và domain guard vẫn được giữ nguyên.

Tasks:

- Selector set primary/fallback.
- Known popup handler.
- Mở disease menu/list.
- Page classifier cho detail/list/home/login/blocked/unknown.
- Navigation detection loop và route theo page type.
- Loop guard: max hops, visited fingerprint và no-progress.
- Navigation timeout/retry.
- Evidence screenshot khi lỗi.
- Safety validation domain/redirect.

Acceptance:

- Từ session hợp lệ đến đúng disease list.
- Chỉ cho phép crawl khi classifier xác nhận `DISEASE_DETAIL`.
- Nếu đang ở list/home/unknown, crawler tìm candidate và lặp navigation.
- Repeated page/no-progress kết thúc bằng lỗi có phân loại, không loop vô hạn.
- Popup fixture không chặn navigation.
- Selector fail được classify.
- Không navigation ra ngoài allowed domain.

### Day 4 — Discovery

Status: **DONE — LIVE VALIDATED 2026-07-28**. Authenticated listing được nhận
diện đúng trên cây menu thật; discovery giới hạn lấy 9 disease items/9 ID duy
nhất, dừng ở `last_page`, không chạm limit và xuất atomic
`disease-list.json` đầy đủ field.

Tasks:

- Pagination/load-more strategy.
- Candidate selection ưu tiên link chưa visited trong detection loop.
- URL canonicalization và item ID.
- Dedup trong job.
- Persist discovered item vào SQLite.
- Export `disease-list.json`.
- Max page/item và loop detection.

Acceptance:

- Resume discovery không duplicate.
- Output có ID, title hint, canonical URL.
- Dừng đúng ở last page hoặc safety limit.
- Report warning nếu chạm limit.
- Candidate đã visited không bị chọn lặp lại trong cùng attempt.

### Day 5 — Detail fetching

Status: **DONE — LIVE VALIDATED 2026-07-28**. Một disease detail thật được
xác nhận confidence `1.0`, lưu atomic raw HTML 30,463 bytes và masked screenshot
311,257 bytes. Manifest/hash/permission `0600` đều hợp lệ; lần invoke thứ hai
reuse artifact với tổng cộng một attempt.

Tasks:

- Item subgraph đến `persist_raw`.
- Content-ready marker.
- Raw HTML và screenshot atomic.
- Attempt record và network retry.
- Artifact manifest bản đầu.

Acceptance:

- Crawl được sample item.
- Raw/screenshot có checksum.
- Network failure retry đúng policy.
- Restart sau raw write không làm mất artifact.

### Day 6 — Batch and checkpoint

Status: **DONE — LIVE VALIDATED 2026-07-29**. Live batch chạy qua hai browser
phase: phase 1 fetch một bệnh rồi pause/cleanup; phase 2 resume không refetch
item đầu, fetch bệnh tiếp theo, ghi nhận một lỗi `PAGE_TYPE_UNKNOWN` có kiểm
soát và tiếp tục đến `completed_with_errors`. Hai raw artifact set đều hợp lệ.

Tasks:

- Select-next loop.
- Per-item checkpoint.
- Continue-on-error.
- Graceful shutdown/pause.
- Resume recovery matrix cho fetched items.

Acceptance:

- Batch sample chạy hết khi một item lỗi.
- Kill/restart có kiểm soát và resume đúng item.
- Không crawl lại item đã completed.
- Browser/context luôn cleanup.

### Day 7 — Cleaning and Markdown

Status: **DONE — LIVE DATA VALIDATED 2026-07-29**. Hai raw checkpoint thật từ
Day 6 được xử lý offline thành `content.html` và Markdown ổn định. Cả hai không
còn tag/marker giao diện, giữ được heading/list/table/link, có content hash khớp
manifest và được reuse khi chạy lại. Chi tiết:
[Day7-Implementation-Report.md](Day7-Implementation-Report.md).

Tasks:

- Content root plugin.
- Generic extractor fallback.
- HTML sanitizer/cleaner.
- Markdown conversion và canonicalization.
- Content hash.
- Fixture cho headings, list, table, link.

Acceptance:

- Markdown không chứa menu/script/footer đã biết.
- Heading/list/table quan trọng được giữ.
- Cùng content tạo cùng hash.
- Content rỗng không được đánh dấu success.

### Day 8 — Structured parsing

Status: **DONE — LIVE DATA VALIDATED 2026-07-29**. Hai Markdown thật từ Day 7
được chuyển thành `disease.json` schema v1 bằng parser rules không gọi dịch vụ
bên ngoài. Provenance/content hash/schema hash đều khớp, giá trị không grounded
bị chặn, field thiếu giữ `null`/`[]`, và checkpoint được reuse khi chạy lại.
Chi tiết: [Day8-Implementation-Report.md](Day8-Implementation-Report.md).

Tasks:

- Pydantic disease schema.
- Versioned parser prompt.
- Structured model client.
- Chunk-by-heading và deterministic merge.
- Validation/warning/no-hallucination guard.
- Model fake tests.

Acceptance:

- Sample Markdown tạo JSON đúng schema.
- Field thiếu trả `null`/`[]`.
- Source/provenance luôn có.
- Invalid model output không ghi đè kết quả tốt.

### Day 9 — Integration and MVP release

Status: **DONE — TECHNICAL RELEASE CANDIDATE VALIDATED 2026-07-29**. Final
`report.json` và `job.json` đã được tạo từ job thật với hai artifact set hoàn
chỉnh và một lỗi có kiểm soát. API create/status/report, repair-once và E2E
replay ba item đều pass. D-02 đã được owner xác nhận ngày 2026-07-29; live crawl
có kiểm soát được phép trong phạm vi nội bộ. Chi tiết:
[Day9-Implementation-Report.md](Day9-Implementation-Report.md).

Tasks:

- Validation repair tối đa một lần.
- Final manifest/report.
- API create/status/report.
- E2E smoke 1–3 item.
- README vận hành và known limitations.
- Kiểm tra full DoD.

Acceptance:

- Demo end-to-end login → export.
- Output đủ raw/Markdown/JSON/screenshot.
- Item lỗi xuất hiện trong report.
- Test suite và quality gates pass.

## 3. V2 — 7 ngày

### V2 Day 1 — Plugin hardening

- Tách mọi logic site-specific khỏi core.
- Plugin registry/capabilities.
- Fake second plugin để chứng minh core không coupling.
- Contract tests dùng chung cho plugin.

### V2 Day 2 — Resume hardening

- Recovery reconciliation DB ↔ artifact.
- Integrity checks/checksums.
- Pause/resume API/CLI.
- Test crash injection tại từng checkpoint.

### V2 Day 3 — Reliability

- Full error taxonomy.
- Backoff/jitter/circuit breaker.
- Failed queue và filtered retry.
- Error-rate auto-pause.

### V2 Day 4 — Vision fallback

- Screenshot redaction.
- Vision structured output.
- Confidence/action/domain guard.
- Before/after validation.
- Budget metrics và tests bằng fixtures.

### V2 Day 5 — Incremental crawl

- Document version repository.
- Content/schema hash.
- Unchanged skip.
- Duplicate content mapping.
- Possibly-removed report.

### V2 Day 6 — CLI and export

- Toàn bộ command trong API/CLI plan.
- JSON output/exit codes.
- JSONL export/checksum.
- Operator runbook.

### V2 Day 7 — Packaging/release

- Docker non-root.
- Persistent volumes và healthcheck.
- Config/security validation.
- Staging smoke và crawl report.
- Release checklist, migration/rollback guide.

## 4. Work breakdown theo epic

| Epic | Deliverable | Dependency |
|---|---|---|
| E1 Foundation | app skeleton, config, DB, logging | không |
| E2 Browser/session | Playwright lifecycle, login | E1 + credential |
| E3 Plugin/discovery | list disease | E2 + DOM fixture |
| E4 Fetch/storage | raw evidence | E3 |
| E5 Parse | Markdown + disease JSON | E4 + schema approval |
| E6 Orchestration | batch/retry/resume | E1, E4, E5 |
| E7 Interfaces | API/CLI/export | E6 |
| E8 Production hardening | Vision/incremental/Docker | E6, E7 |

## 5. Definition of Done

### MVP DoD

- Auto login và session reuse.
- Discover toàn bộ danh sách trong giới hạn được cấu hình.
- Crawl detail theo batch.
- Mỗi item thành công có `raw.html`, `markdown.md`, `disease.json`,
  `screenshot.png`, `manifest.json`.
- JSON pass Pydantic schema và có provenance.
- Item lỗi không làm mất toàn job.
- Job report chính xác.
- Core unit/integration tests pass và E2E smoke pass.
- Không lộ secret.

### V2 DoD

- Core không phụ thuộc plugin cụ thể.
- Resume được chứng minh bằng crash-injection tests.
- Retry/failed queue hoạt động theo taxonomy.
- Incremental unchanged không gọi parser model.
- Vision chỉ chạy sau deterministic fallback và có guardrail.
- CLI, API, Docker và operator runbook hoàn chỉnh.
- Staging report không có blocker severity cao.

## 6. Rủi ro và phương án

| Rủi ro | Dấu hiệu | Giảm thiểu |
|---|---|---|
| DOM thay đổi | selector fail tăng | selector set, fixture, Vision cuối |
| CAPTCHA/block | page marker/block response | pause, giảm rate, operator |
| Session ngắn | auth error giữa batch | validate và relogin một lần |
| Nội dung quá dài | model/token failure | chunk theo heading |
| Model bịa dữ liệu | field không có nguồn | prompt constraint, warnings, review |
| Duplicate/rename | name/path collision | canonical URL hash ID |
| Crash/partial file | DB/file lệch | atomic write + reconciliation |
| SQLite contention | locked DB | single writer/instance |
| Chi phí AI cao | nhiều unchanged/model calls | hash, rule parsing, budgets |
| Quyền nội dung | phạm vi/quyền thay đổi | lưu xác nhận và rà lại định kỳ |

## 7. Decision baseline đã được phê duyệt

Owner đã chấp thuận D-01 đến D-08 theo phương án đề xuất và bổ sung D-09 theo
yêu cầu về detection loop. Các quyết định dưới
đây là baseline bắt buộc cho MVP/V2:

| ID | Quyết định đã chốt | Trạng thái | Điều kiện thực thi |
|---|---|---|---|
| D-01 | Dùng disease schema v1 tại `02-data-and-storage.md`; thay đổi field phải tăng schema version | APPROVED | triển khai trước Day 8 |
| D-02 | Chỉ crawl/lưu khi quyền truy cập và quyền sử dụng nội dung đã được xác nhận | OWNER CONFIRMED 2026-07-29 | được phép automation và lưu HTML/PNG/Markdown/JSON cho mục đích nội bộ |
| D-03 | Khởi đầu 1 browser context và 1 page/domain; delay có jitter; mọi job có `max_items`/`max_pages` | APPROVED | đo staging trước khi tăng concurrency |
| D-04 | Giữ mọi version raw HTML và screenshot trong MVP/V2; chưa tự động cleanup | APPROVED | rà lại dung lượng/retention trước production |
| D-05 | API MVP chỉ chạy local/internal; không public exposure nếu chưa có authentication/authorization | APPROVED | kiểm tra deployment topology trước deploy |
| D-06 | Model được cấu hình theo capability, không hard-code; job có timeout và call/token budget | APPROVED | validate model thực tế trước Day 8 |
| D-07 | Vision tối đa 2 action/item, confidence mặc định ≥ `0.85`, chỉ chạy sau deterministic fallback | APPROVED | bật bằng feature flag từ V2 Day 4 |
| D-08 | Giữ nguyên ngôn ngữ của nguồn trong Markdown/JSON; không tự động dịch ở MVP/V2 | APPROVED | schema/output test phải kiểm tra không dịch |
| D-09 | Chỉ crawl sau khi page classifier xác nhận `DISEASE_DETAIL`; mọi page type khác phải route qua detection loop có loop guard | APPROVED | triển khai và test trong Day 3 |

Lưu ý: owner đã xác nhận website/tài khoản cụ thể cho phép automation và lưu nội
dung ngày 2026-07-29. Nếu phạm vi tài khoản, hợp đồng hoặc điều khoản website
thay đổi, D-02 phải được rà soát lại trước lần crawl tiếp theo.

### Input readiness

| Input | Trạng thái | Ghi chú |
|---|---|---|
| Tài khoản website thật | AVAILABLE | owner confirmed; không lưu credential trong plan/Git |
| Credential runtime | AVAILABLE | được đọc từ `.env`; không hiển thị/log giá trị |
| Playwright session state | AVAILABLE | live login + reuse đã pass; file permission `0600` |
| Quyền automation/lưu nội dung | AVAILABLE | owner confirmed 2026-07-29; mục đích nội bộ |
| HTML/screenshot fixtures | PENDING COLLECTION | thu thập sau khi browser/session skeleton sẵn sàng |

## 8. Release checklist

- [ ] Migration backup/restore đã test.
- [x] Credential và session path không nằm trong Git.
- [x] Allowed domains đúng.
- [x] Crawl limits không để vô hạn.
- [x] Model budget và timeout được cấu hình.
- [x] Unit/integration/smoke tests pass.
- [x] Artifact sample được reviewer đối chiếu nguồn.
- [x] Resume test pass.
- [x] Error report dễ hành động.
- [x] D-02 có xác nhận quyền crawl/lưu cho website và tài khoản thực tế.
- [ ] Rollback image/version có sẵn.
