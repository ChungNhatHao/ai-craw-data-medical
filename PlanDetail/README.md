# AI Medical Crawler — Detailed Implementation Plan

## 1. Mục đích

Thư mục này chuyển `AI_Medical_Crawler_MVP_V2_Plan.md` thành kế hoạch triển
khai có thể giao việc, code, kiểm thử và nghiệm thu.

Phạm vi hiện tại:

```text
Login → Discover → Navigate → Fetch → Extract → Clean → Parse → Validate
      → Persist → Report
```

Không bao gồm Knowledge Base, embedding, Vector Database, RAG hoặc chatbot.

## 2. Nguyên tắc thiết kế đã chốt

1. **Deterministic-first:** dùng selector, rule và parser thông thường trước.
   LLM/Vision chỉ xử lý phần không ổn định hoặc không thể xác định bằng rule.
2. **Plugin-first:** core không chứa selector hoặc logic riêng của
   `genre-manuals.com`.
3. **Artifact-first:** lưu bằng chứng gốc trước khi biến đổi để có thể audit và
   parse lại mà không crawl lại.
4. **Resumable:** mỗi item có state bền vững; tiến trình bị dừng không làm mất
   kết quả đã hoàn tất.
5. **Idempotent:** chạy lại cùng một item không tạo dữ liệu trùng hoặc phá dữ
   liệu tốt trước đó.
6. **Traceable:** mọi JSON phải truy ngược được URL nguồn, thời điểm crawl,
   phiên bản parser, prompt và schema.
7. **No hallucination:** trường không có trong nguồn phải là `null` hoặc `[]`;
   model không được tự bổ sung kiến thức y khoa.

## 3. Các quyết định mặc định

| Chủ đề | Quyết định |
|---|---|
| Runtime | Python 3.12, async |
| API | FastAPI |
| Workflow | LangGraph |
| Browser | Playwright Chromium |
| Checkpoint/metadata | SQLite |
| Artifact | Filesystem |
| Validation | Pydantic v2 |
| HTML cleaning | BeautifulSoup/lxml + Trafilatura fallback |
| Structured parsing | Rule-based trước, LLM structured output sau |
| Vision | Fallback cuối, không dùng ở happy path |
| Item ID | SHA-256 của canonical URL |
| Incremental detection | Hash Markdown đã canonicalize |
| Concurrency ban đầu | 1 browser context, 1 page/domain |
| Retry | Theo loại lỗi, exponential backoff + jitter |
| Secret | Environment variables; không commit cookie/credential |

Các quyết định D-01 đến D-09 trong roadmap đã được owner chấp thuận theo phương
án đề xuất và trở thành baseline triển khai. Thay đổi các quyết định này phải
được ghi lại trong decision log hoặc pull request tương ứng.

## 4. Bản đồ tài liệu

1. [01-scope-and-architecture.md](01-scope-and-architecture.md): phạm vi,
   component, luồng dữ liệu và cấu trúc source code.
2. [02-data-and-storage.md](02-data-and-storage.md): schema, SQLite, artifact,
   hashing và quy tắc ghi dữ liệu.
3. [03-workflow-and-reliability.md](03-workflow-and-reliability.md): LangGraph,
   state machine, retry, resume và incremental crawl.
4. [04-plugin-and-browser.md](04-plugin-and-browser.md): plugin contract,
   login, navigation, selector, popup và Vision fallback.
5. [05-api-cli-and-configuration.md](05-api-cli-and-configuration.md): API, CLI,
   config, job lifecycle và Docker.
6. [06-testing-observability-security.md](06-testing-observability-security.md):
   test strategy, logging, metrics, security và compliance.
7. [07-delivery-roadmap.md](07-delivery-roadmap.md): backlog theo ngày, tiêu chí
   nghiệm thu, rủi ro và Definition of Done.
8. [Day1-Implementation-Report.md](Day1-Implementation-Report.md): kết quả và
   bằng chứng hoàn thành MVP Day 1.
9. [Day2-Implementation-Report.md](Day2-Implementation-Report.md): kết quả phần
   login/session và bước live validation còn lại của MVP Day 2.
10. [Day3-Implementation-Report.md](Day3-Implementation-Report.md): page
    classifier, navigation detection loop và phần authenticated validation còn lại.
11. [Day4-Implementation-Report.md](Day4-Implementation-Report.md): pagination,
    URL identity, dedup, persistence/export và authenticated validation còn lại.
12. [08-gemini-agentic-flow-implementation.md](08-gemini-agentic-flow-implementation.md):
    kế hoạch nâng cấp observe/navigation/disease extraction/normalization bằng
    Gemini với BeautifulSoup-first cleaning, safe browser tools, grounding và
    rollout có feature flag.
13. [Gemini-Agentic-Implementation-Report.md](Gemini-Agentic-Implementation-Report.md):
    trạng thái triển khai offline, bằng chứng kiểm thử và credential gate còn lại.

## 5. Cổng bắt đầu triển khai

Trước khi crawl dữ liệu thật, đội triển khai cần hoàn tất:

- Tài khoản hợp lệ để đăng nhập website thật: **AVAILABLE — owner confirmed**.
- Khi triển khai, cung cấp username/password qua `.env` hoặc secret mechanism;
  không ghi credential vào tài liệu, source code, log hoặc commit.
- Quyền truy cập, automation và lưu/xử lý nội dung nguồn theo D-02:
  **AVAILABLE — owner confirmed 2026-07-29**.
- Xác nhận website đích và các môi trường cần hỗ trợ.
- Thu thập tối thiểu 3 HTML fixture: trang login, danh sách bệnh, chi tiết bệnh.
- Kiểm tra người sử dụng dữ liệu chấp nhận schema v1 đã duyệt tại D-01.
- Áp dụng giới hạn crawl đã duyệt tại D-03 và cấu hình thêm `max_items`,
  `max_pages` cho từng job.

Các điều kiện vận hành chưa hoàn tất không ngăn việc dựng skeleton, test fixtures
và core engine, nhưng ngăn việc chạy full crawl trên website thật.

## 6. Quy ước trạng thái kế hoạch

Mỗi task trong roadmap sử dụng:

- `TODO`: chưa bắt đầu.
- `IN PROGRESS`: đang thực hiện.
- `BLOCKED`: thiếu input hoặc quyền.
- `DONE`: code, test và tài liệu nghiệm thu đều hoàn tất.

Một task không được đánh dấu `DONE` nếu chỉ chạy được bằng thao tác thủ công
không được ghi lại.
