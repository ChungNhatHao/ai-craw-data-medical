# 08 — Gemini Agentic Crawl Flow Implementation Plan

## 1. Mục tiêu

Nâng pipeline hiện tại thành một workflow có Gemini hỗ trợ điều hướng, xác minh
trang bệnh, trích xuất và chuẩn hóa, nhưng vẫn giữ browser execution, lưu
artifact, validation và các giới hạn an toàn ở code deterministic.

Flow mục tiêu đã hiệu chỉnh:

```text
Website + authenticated Playwright session
  → observe_page (Content Extractor không AI)
  → Navigation Agent (Gemini)
  → deterministic Browser Executor
  → observe_page lại sau mỗi navigation
  → Disease Detector (Gemini)
      ├─ không phải trang bệnh → quay lại Navigation Agent
      └─ là trang bệnh
          → persist raw evidence
          → BeautifulSoup HTML Cleaner (không AI)
          → clean content/Markdown
          → Disease Extraction Agent (Gemini)
          → deterministic normalization
          → Normalization Agent (Gemini, chỉ cho trường mơ hồ)
          → Pydantic/grounding validation
              ├─ invalid → repair một lần hoặc failed
              └─ valid → Structured JSON + report
```

Điểm quan trọng:

- Content Extractor không phải một bước chạy một lần. Nó là node
  `observe_page`, chạy lại sau mỗi lần URL hoặc DOM state thay đổi.
- Raw HTML không bao giờ là input của Normalization Agent. BeautifulSoup phải
  sanitize và trích main content trước; AI chỉ nhận clean text/Markdown và các
  field đã được deterministic parser tạo ra.

## 2. Đánh giá kiến trúc

### 2.1 Phần giữ nguyên

- Playwright login, session reuse và domain allowlist.
- Browser Manager và plugin selector.
- Raw HTML, screenshot, Markdown và manifest.
- SQLite job/item/attempt checkpoint.
- Disease schema v1 và Pydantic validation.
- Grounding guard, field thiếu trả `null` hoặc `[]`.
- Batch fetch, cleaning, reporting và Web Operator Console.

### 2.2 Phần cần thay đổi

- Thay navigation decision hiện tại bằng strategy có Gemini fallback.
- Tách rõ `Disease Detector` khỏi `Disease Extraction Agent`.
- Thêm Gemini client dùng chung và model policy cho từng agent.
- Mở rộng LangGraph state để chứa observation, decision và AI budgets.
- Thêm artifact audit cho từng Gemini call và quyết định agent.
- Thêm deterministic normalizer trước khi gọi Normalization Agent.
- Đặt `BeautifulSoupContentCleaner` thành boundary bắt buộc giữa raw HTML và
  mọi Gemini agent xử lý nội dung.
- Thêm UI hiển thị vòng lặp observe/navigate/detect.

### 2.3 Nguyên tắc bắt buộc

1. Model chỉ đề xuất; code thực thi và kiểm tra quyền.
2. Không gửi credential, cookie, header hoặc toàn bộ storage state cho Gemini.
3. Không cho model tự tạo URL ngoài candidate do extractor cung cấp.
4. Chỉ `Disease Detector` xác nhận mới được chạy Disease Extraction Agent.
5. Không dùng kiến thức y khoa bên ngoài nội dung nguồn.
6. Mọi giá trị Structured JSON phải truy được về evidence trong artifact.
7. Mọi vòng lặp và model call đều có giới hạn.
8. Disease Extraction và Normalization Agent không được nhận raw HTML.

## 3. Kiến trúc component

```text
Web UI / Jobs API
        │
        ▼
AgenticPipelineRunner
        │
        ├── BrowserSession
        ├── PageObserver (no AI)
        ├── GeminiClient
        │     ├── NavigationAgent
        │     ├── DiseaseDetector
        │     ├── DiseaseExtractionAgent
        │     └── NormalizationAgent
        ├── SafeBrowserExecutor (no AI)
        ├── BeautifulSoupContentCleaner (no AI)
        ├── DeterministicNormalizer
        ├── GroundingValidator
        ├── PydanticSchemaValidator
        ├── Repositories
        └── ArtifactStore
```

Một `GeminiClient` dùng chung API key. Mỗi agent có prompt, schema, model config,
timeout và budget riêng; không cần API key riêng.

## 4. Data contract trung gian

### 4.1 PageObservation

`PageObserver` tạo snapshot gọn, không gửi raw HTML đầy đủ mặc định:

```python
class PageObservation(BaseModel):
    url: HttpUrl
    canonical_url: HttpUrl
    title: str | None
    breadcrumb: tuple[str, ...]
    headings: tuple[str, ...]
    main_text_excerpt: str
    medical_section_markers: tuple[str, ...]
    links: tuple[ObservedLink, ...]
    forms: tuple[ObservedForm, ...]
    page_fingerprint: str
```

`ObservedLink` gồm `candidate_id`, label, URL canonical, DOM region và điểm rule.
Gemini chỉ được chọn `candidate_id`; không được trả URL tùy ý.

Giới hạn đề xuất:

- Tối đa 80 link/observation.
- Tối đa 12.000 ký tự text cho Navigation Agent.
- Tối đa 30.000 ký tự cho Disease Detector.
- Raw HTML chỉ lưu local, không gửi model.

### 4.2 NavigationDecision

```python
class NavigationDecision(BaseModel):
    action: Literal["open_candidate", "go_back", "stop", "needs_operator"]
    candidate_id: str | None
    confidence: float
    reason_code: Literal[
        "medical_category",
        "disease_candidate",
        "pagination",
        "no_candidate",
        "blocked",
    ]
```

Backend validation:

- `candidate_id` phải có trong observation hiện tại.
- URL đích phải thuộc allowlist.
- Candidate chưa được visited.
- Action không vượt hop/page budget.
- Model không trực tiếp click hoặc gọi Playwright.

### 4.3 DiseaseDecision

```python
class DiseaseDecision(BaseModel):
    is_disease_detail: bool
    confidence: float
    disease_name: str | None
    evidence: tuple[str, ...]
    negative_signals: tuple[str, ...]
    reason_code: Literal[
        "confirmed_detail",
        "listing_page",
        "menu_page",
        "login_page",
        "blocked_page",
        "insufficient_content",
    ]
```

Acceptance mặc định:

```text
rule classifier không phát hiện login/block
AND Gemini is_disease_detail = true
AND confidence >= 0.85
AND có title/content root
AND có tối thiểu hai medical section marker hoặc evidence tương đương
```

Nếu rule và Gemini xung đột, không crawl ngay. Trang chuyển sang `UNKNOWN`, lưu
evidence và thử candidate khác. Không để Gemini override login/CAPTCHA/domain
guard.

### 4.4 DiseaseDraft

Disease Extraction Agent trả schema trung gian có evidence theo từng field:

```python
class EvidenceValue(BaseModel):
    value: str
    source_quote: str
    source_section: str | None

class DiseaseDraft(BaseModel):
    name: EvidenceValue
    aliases: tuple[EvidenceValue, ...]
    summary: EvidenceValue | None
    causes: tuple[EvidenceValue, ...]
    risk_factors: tuple[EvidenceValue, ...]
    symptoms: tuple[EvidenceValue, ...]
    diagnosis: tuple[EvidenceValue, ...]
    treatment: tuple[EvidenceValue, ...]
    prevention: tuple[EvidenceValue, ...]
    prognosis: EvidenceValue | None
    when_to_seek_care: tuple[EvidenceValue, ...]
```

`source_quote` là bằng chứng nội bộ để grounding, không nhất thiết xuất ra schema
v1 cho người dùng.

### 4.5 CleanContent và NormalizationInput

BeautifulSoup tạo artifact trung gian:

```python
class CleanContent(BaseModel):
    source_url: HttpUrl
    title: str | None
    headings: tuple[str, ...]
    clean_html: str
    markdown: str
    plain_text: str
    removed_node_count: int
    content_hash: str

class NormalizationInput(BaseModel):
    source_url: HttpUrl
    content_hash: str
    draft: DiseaseDraft
    ambiguous_fields: tuple[str, ...]
    evidence_text: str
```

`NormalizationInput` không có field `raw_html`. `evidence_text` chỉ được dựng từ
`CleanContent.plain_text` hoặc Markdown đã sanitize. Payload builder phải reject
nếu phát hiện marker raw document như `<!doctype`, `<html`, `<body>`, `<script>`
hoặc `<form>`.

### 4.6 NormalizationResult

```python
class NormalizationResult(BaseModel):
    normalized_draft: DiseaseDraft
    changed_fields: tuple[str, ...]
    ambiguous_fields: tuple[str, ...]
    warnings: tuple[str, ...]
```

Không dịch ngôn ngữ, suy diễn chẩn đoán hoặc bổ sung kiến thức ngoài nguồn trong
phase đầu.

## 5. Trách nhiệm từng agent

### 5.1 Navigation Agent

Input:

- Observation hiện tại.
- Page type rule-based.
- Candidate links đã xếp hạng.
- Breadcrumb, visited IDs, hop budget còn lại.
- Mục tiêu: tìm thêm trang bệnh chưa thu thập.

Output: `NavigationDecision`.

Gemini dùng function calling hoặc structured decision để chọn một action.
Backend thực thi tool. Function/tool allowlist:

- `open_candidate(candidate_id)`
- `go_back()`
- `stop(reason_code)`
- `request_operator(reason_code)`

Navigation Agent không nhận username/password và không được submit form.

### 5.2 Disease Detector

Input:

- URL/title/breadcrumb.
- Main text đã làm sạch.
- Heading/section markers.
- Link density và rule classification.

Output: `DiseaseDecision`.

Prompt phải phân biệt:

- Một bệnh cụ thể.
- Danh mục nhiều bệnh.
- Bài viết chung/medical guideline.
- Calculator/questionnaire.
- Login, blocked, empty hoặc error page.

### 5.3 Disease Extraction Agent

Chỉ chạy khi Detector đã xác nhận. Input ưu tiên Markdown đã clean/chunk theo
heading do BeautifulSoup pipeline tạo ra. Agent không nhận raw HTML. Output là
`DiseaseDraft` có evidence.

Quy tắc prompt:

- Chỉ lấy nội dung xuất hiện trong input.
- Không sử dụng kiến thức đã biết của model.
- Không suy đoán.
- Field thiếu trả `null` hoặc danh sách rỗng.
- Không gộp nội dung của hai bệnh khác nhau.

### 5.4 Normalization Agent

Chỉ nhận `NormalizationInput`: các trường mà deterministic normalizer đánh dấu
`ambiguous` và evidence text đã qua BeautifulSoup. Agent không có quyền truy cập
raw HTML, DOM, browser page hoặc artifact `raw.html`.

Được phép:

- Tách list bị dính.
- Gộp duplicate có cùng nghĩa và cùng evidence.
- Chuẩn hóa khoảng trắng, punctuation, casing.
- Chọn canonical label từ những giá trị đã có trong nguồn.

Không được phép:

- Tạo fact mới.
- Dịch hoặc diễn giải vượt nguồn.
- Thay đổi con số, liều lượng hoặc điều kiện y khoa.
- Xóa evidence.

## 6. Deterministic processing

### 6.1 PageObserver

Thứ tự extractor:

1. Plugin selectors.
2. Semantic HTML: `main`, `article`, headings, breadcrumb.
3. Generic link/form extraction.
4. Trafilatura fallback cho main text.
5. Sanitize script/style/account/menu không liên quan.
6. Canonicalize URL và hash observation.

### 6.2 SafeBrowserExecutor

- Chỉ nhận validated `NavigationDecision`.
- Kiểm tra scheme/domain trước và sau navigation.
- Dismiss popup thuộc allowlist.
- Chờ `domcontentloaded` và content-ready marker.
- Capture screenshot/trace khi lỗi.
- Tăng hop counter bằng code, không lấy từ model.

### 6.3 BeautifulSoup HTML cleaning

Trước extraction/normalization, raw HTML bắt buộc đi qua:

1. Parse bằng `BeautifulSoup(..., "lxml")`.
2. Chọn content root theo plugin selector.
3. Xóa `script`, `style`, `noscript`, navigation, footer, form, account/logout,
   cookie banner và node ẩn đã biết.
4. Giữ heading, paragraph, list, table và link nội dung.
5. Sanitize attribute và URL.
6. Tạo `content.html`, Markdown và plain text.
7. Tạo content hash và ghi manifest.
8. Chỉ các artifact đã clean mới được chuyển cho Gemini content agents.

Nếu selector plugin không tìm được content root, dùng generic extractor rồi
Trafilatura fallback. Nếu vẫn không đạt minimum content length, trả
`CONTENT_EMPTY`; không gửi raw HTML cho Gemini để model tự tìm nội dung.

### 6.4 DeterministicNormalizer

Chạy trước Normalization Agent:

- Unicode NFC.
- Whitespace và line ending.
- Deduplicate exact/case-insensitive.
- Chuẩn hóa empty value.
- URL canonicalization.
- Danh sách/table parsing rõ ràng.
- Giữ nguyên số, đơn vị và text y khoa.

Nếu không có trường ambiguous thì bỏ qua hoàn toàn Normalization Agent.

### 6.5 Final validation

1. Validate Gemini response bằng schema.
2. Ground từng `value` và `source_quote` vào Markdown nguồn.
3. Validate DiseaseDocument bằng Pydantic.
4. Kiểm tra schema hash, content hash và provenance.
5. Repair tối đa một lần.
6. Invalid lần hai: không ghi đè artifact tốt; lưu failed attempt.

Structured output bảo đảm định dạng, không thay thế semantic validation trong
ứng dụng.

## 7. LangGraph workflow

```text
initialize
 → authenticate
 → observe_page
 → rule_classify
 → disease_detect
    ├─ confirmed
    │    → persist_raw
    │    → beautifulsoup_clean_html
    │         ├─ empty/invalid → alternate_extractor hoặc fail_item
    │         └─ clean artifact
    │    → disease_extract
    │    → deterministic_normalize
    │    → has_ambiguity?
    │         ├─ yes → ai_normalize
    │         └─ no
    │    → validate_grounding
    │         ├─ invalid + repair budget → repair_once
    │         ├─ invalid → fail_item
    │         └─ valid → persist_json
    │    → target_reached?
    │         ├─ yes → report
    │         └─ no → restore_discovery_context
    │
    └─ not confirmed
         → navigation_decide
         → validate_action
             ├─ invalid → reject_decision → navigation_decide
             └─ valid → execute_action
         → observe_page
```

Loop guards:

- `max_navigation_hops = 30/job` cho thử nghiệm đầu.
- `max_pages_evaluated = max(max_items * 8, 30)`, vẫn bị chặn bởi hard limit.
- `max_same_fingerprint = 3`.
- `max_invalid_agent_decisions = 2/page`.
- `max_gemini_calls` theo job và theo agent.
- Hai vòng không tạo URL/fingerprint mới: stop hoặc chuyển candidate.

## 8. Gemini integration

### 8.1 Dependency và client

- Dùng SDK Python chính thức `google-genai`.
- Tạo một `GeminiClient` async wrapper.
- Dùng structured output/Pydantic cho mọi response.
- Function calling cho Navigation Agent.
- Model name nằm trong config, không hardcode trong prompt/service.
- Adapter/protocol cho phép fake client trong test.

Google khuyến nghị dùng function calling khi model cần yêu cầu ứng dụng thực
hiện hành động, và structured outputs khi cần response theo schema.

### 8.2 Configuration

```text
GEMINI_API_KEY=
GEMINI_NAVIGATION_MODEL=
GEMINI_DETECTOR_MODEL=
GEMINI_EXTRACTION_MODEL=
GEMINI_NORMALIZATION_MODEL=
GEMINI_TIMEOUT_SECONDS=30
GEMINI_MAX_RETRIES=2
GEMINI_MAX_CALLS_PER_JOB=100
GEMINI_MAX_INPUT_CHARS=30000
GEMINI_DISEASE_CONFIDENCE_THRESHOLD=0.85
AGENTIC_DISCOVERY_ENABLED=false
AI_NORMALIZATION_ENABLED=false
```

Khuyến nghị ban đầu: dùng cùng một model Flash-class ổn định cho ba agent, chỉ
tách model sau khi có eval chứng minh lợi ích. Model ID cụ thể được chốt tại
thời điểm triển khai để tránh pin nhầm preview/retired model.

### 8.3 Secret

- API key chỉ đọc từ environment hoặc secret manager ở backend.
- Không thêm Gemini key vào form Web UI.
- Không trả key trong exception, health endpoint, snapshot hoặc report.
- Redact query/header/body trước khi log.
- Production dùng key bị giới hạn và billing alert.

## 9. Persistence và artifact audit

Artifact mới theo job/item:

```text
jobs/{job_id}/
  agent-summary.json
  navigation-trace.ndjson
  observations/
    {fingerprint}.json
  items/{slug--id}/
    disease-decision.json
    disease-draft.json
    normalization.json
    disease.json
```

Mỗi model call lưu metadata, không lưu secret:

```json
{
  "agent": "disease_detector",
  "model_id": "...",
  "prompt_version": "1.0.0",
  "input_hash": "...",
  "output_hash": "...",
  "latency_ms": 0,
  "input_tokens": 0,
  "output_tokens": 0,
  "cached": false,
  "status": "success"
}
```

Migration đề xuất:

- `agent_decisions`: job/item, agent, page fingerprint, decision, confidence.
- `model_calls`: model, prompt version, tokens, latency, status, error code.
- Index theo `(job_id, agent_name)` và `(input_hash, prompt_version, model_id)`.

Không lưu chain-of-thought. Chỉ lưu structured decision, reason code và evidence
do schema yêu cầu.

## 10. API và Web UI

### 10.1 Run request

Thêm:

```json
{
  "agentic_discovery": true,
  "ai_normalization": true,
  "max_items": 10
}
```

Không nhận Gemini key qua request.

### 10.2 Progress

UI hiển thị các stage:

```text
Observe page
AI navigation
Disease verification
Fetch evidence
Disease extraction
Normalization
Schema validation
Report
```

Thông tin live:

- URL/candidate đang xét, đã sanitize.
- Số trang quan sát.
- Số disease accepted/rejected.
- Gemini calls/budget còn lại.
- Rule/model confidence.
- Lý do loại trang.

### 10.3 Output

Thêm link:

- Agent trace.
- Disease decision.
- Draft có evidence.
- Normalization changes.
- Final disease JSON.

## 11. Error taxonomy bổ sung

| Error code | Retry | Xử lý |
|---|---:|---|
| `GEMINI_AUTH_FAILED` | 0 | fail fast, yêu cầu cấu hình key |
| `GEMINI_RATE_LIMITED` | 2 | Retry-After/backoff, sau đó pause |
| `GEMINI_TIMEOUT` | 2 | backoff |
| `GEMINI_OUTPUT_INVALID` | 1 | repair schema |
| `AGENT_ACTION_INVALID` | 1 | reject action, reprompt với lỗi |
| `AGENT_BUDGET_EXHAUSTED` | 0 | fallback rule hoặc partial report |
| `DISEASE_NOT_CONFIRMED` | 0 | tiếp tục discovery |
| `GROUNDING_FAILED` | 1 | repair một lần rồi fail item |
| `NORMALIZATION_CONFLICT` | 0 | giữ deterministic draft + warning |

Circuit breaker:

- Ba lỗi Gemini auth liên tiếp: fail job.
- Năm lỗi rate limit liên tiếp: pause job.
- Error rate model trên 50% sau ít nhất 10 calls: tắt agent tương ứng cho job.

## 12. Test strategy

### 12.1 Unit test

- PageObservation loại script/account/credential.
- BeautifulSoup cleaner loại script/style/form/menu/account khỏi content.
- Gemini content payload không chứa raw HTML hoặc raw DOM.
- Payload builder reject `raw_html` và các raw-document marker.
- Candidate ID ổn định và URL canonical.
- Navigation action không thuộc allowlist bị reject.
- Gemini trả URL tự tạo bị reject.
- Disease detector schema và threshold.
- Extraction không grounded bị reject.
- Normalizer không thay đổi số/đơn vị.
- Budget, timeout, retry và circuit breaker.
- Secret redaction.

### 12.2 Contract test

Fake Gemini responses cho:

- Home → chọn Medical.
- List → chọn disease candidate.
- Detail → detector xác nhận.
- Category/article → detector loại.
- Malformed JSON → repair một lần.
- Hallucinated field → grounding fail.
- Missing field → `null`/`[]`.

### 12.3 Integration test

- Fixture flow home → category → list → detail.
- Nhiều bệnh, dedup và resume.
- Model rate limit giữa job.
- Browser navigation thành công nhưng page vẫn là list.
- Conflict rule/Gemini.
- Restart sau disease draft và resume không gọi model lại.

### 12.4 Eval dataset

Tạo tối thiểu:

- 30 disease detail pages.
- 20 disease list/category pages.
- 10 non-disease medical pages.
- 5 login/blocked/error pages.

Metric:

- Disease detector precision mục tiêu `>= 0.98`.
- Recall mục tiêu `>= 0.95`.
- Navigation success tới disease detail `>= 0.90`.
- Grounded field rate `100%`.
- Invalid structured output `< 1%` sau repair.
- Không có secret trong trace/artifact/log.

### 12.5 Live acceptance

Canary 5 bệnh:

- Tìm đủ 5 bệnh.
- Không nhận category/list làm disease.
- 5 disease JSON validate và grounded.
- Job dừng đúng budget.

Sau đó chạy 25 bệnh và so sánh với baseline hiện tại về độ chính xác, thời gian,
Gemini calls và lỗi.

## 13. Lộ trình triển khai đề xuất

### Phase 0 — Decision và credential gate, 0.5 ngày

Status: `BLOCKED — chưa có GEMINI_API_KEY và xác nhận G-01`.

- Tạo/restrict Gemini API key ở môi trường backend.
- Chốt model ID ổn định cho canary.
- Chốt budget/cost và retention model trace.
- Xác nhận nội dung website được phép gửi tới Gemini API.

Acceptance:

- Key không nằm trong source/UI/log.
- Một health check model không chứa dữ liệu bệnh chạy thành công.

### Phase 1 — Gemini foundation, 1 ngày

Status: `DONE — OFFLINE VALIDATED 2026-07-29`.

- Thêm `google-genai`, settings và client protocol.
- Fake Gemini client.
- Timeout/retry/redaction/usage metadata.
- Structured output helper.

Acceptance:

- Unit tests success/timeout/rate-limit/invalid output.
- Không ảnh hưởng flow hiện tại khi feature flag tắt.

### Phase 2 — PageObserver và safe tools, 1 ngày

Status: `DONE — OFFLINE VALIDATED 2026-07-29`.

- Implement `PageObservation`, candidate ID và fingerprint.
- Implement `SafeBrowserExecutor`.
- Observation artifacts.
- Guard URL/action/visited/hop.

Acceptance:

- Gemini không thể mở URL ngoài observation/allowlist.
- Observation không chứa password/cookie.

### Phase 3 — Navigation Agent loop, 1.5 ngày

Status: `DONE — OFFLINE VALIDATED 2026-07-29`.

- Prompt/schema/function declarations.
- LangGraph observe → decide → execute loop.
- Cache decision theo observation hash.
- Loop guards và agent trace.

Acceptance:

- Fixture home/list/detail pass.
- Unknown/repeated page dừng hữu hạn.

### Phase 4 — Disease Detector, 1 ngày

Status: `DONE — OFFLINE VALIDATED 2026-07-29`.

- Detector prompt/schema.
- Kết hợp rule + model decision.
- Confidence threshold và conflict route.
- Disease decision artifact.

Acceptance:

- Eval precision/recall đạt ngưỡng canary.
- Login/list/category không được fetch như disease.

### Phase 5 — Disease Extraction Agent, 1.5 ngày

Status: `DONE — OFFLINE VALIDATED 2026-07-29`.

- Hoàn thiện BeautifulSoup cleaner boundary và clean-content contract.
- Chunk Markdown chỉ từ clean artifact.
- Structured `DiseaseDraft` có evidence.
- Deterministic merge.
- Grounding validation và repair once.

Acceptance:

- Không có field ungrounded.
- Raw HTML không xuất hiện trong Gemini request.
- Field thiếu đúng `null`/`[]`.
- Resume từ draft không gọi Gemini lại.

### Phase 6 — Normalization, 1 ngày

Status: `DONE — OFFLINE VALIDATED 2026-07-29`.

- Deterministic normalizer.
- Ambiguity detector.
- Tạo `NormalizationInput` chỉ từ draft + BeautifulSoup-cleaned evidence.
- Optional Normalization Agent không có raw HTML access.
- Change audit và conflict fallback.

Acceptance:

- Happy path rõ ràng không gọi AI normalization.
- Test chứng minh raw HTML bị reject trước Gemini call.
- Model không tạo fact mới hoặc thay đổi số.

### Phase 7 — UI, observability và live rollout, 1 ngày

Status: `IN PROGRESS — UI/audit/test done; live canary blocked by Phase 0`.

- UI feature flags và agent stages.
- Token/call/latency metrics.
- Agent trace download.
- Canary 5, sau đó 25 bệnh.
- So sánh với baseline.

Acceptance:

- Operator nhìn được từng vòng observe/navigate/detect.
- Full automated tests pass.
- Canary không có list page hoặc hallucinated field.

Tổng ước lượng: 8–9 ngày làm việc cho một developer, chưa tính thời gian duyệt
quyền gửi dữ liệu tới Gemini hoặc tuning eval.

## 14. Rollout

Feature flags:

```text
AGENTIC_DISCOVERY_ENABLED=false
GEMINI_DISEASE_DETECTOR_ENABLED=false
GEMINI_EXTRACTION_ENABLED=false
AI_NORMALIZATION_ENABLED=false
```

Thứ tự bật:

1. Shadow mode: Gemini quyết định nhưng crawler vẫn dùng baseline; chỉ so sánh.
2. Bật Disease Detector.
3. Bật Navigation Agent cho canary 5 item.
4. Bật Disease Extraction Agent.
5. Bật AI Normalization sau khi deterministic normalizer ổn định.
6. Canary 25 item.
7. Mở mặc định sau khi metric đạt ngưỡng.

Rollback chỉ cần tắt feature flag; flow deterministic hiện tại vẫn còn hoạt động.

## 15. Quyết định cần owner xác nhận

| ID | Nội dung | Đề xuất |
|---|---|---|
| G-01 | Cho phép gửi content đã sanitize tới Gemini | Cho phép trong phạm vi nội bộ đã duyệt |
| G-02 | Cách cấp API key | Backend environment/secret manager |
| G-03 | Model ban đầu | Một Flash-class stable model, config ngoài code |
| G-04 | Disease confidence | `0.85`, tune bằng eval |
| G-05 | Model call budget | 100 calls/job trong canary |
| G-06 | Lưu model input | Chỉ hash + observation/draft sanitized; không lưu request chứa secret |
| G-07 | AI normalization | Feature flag, chỉ chạy field ambiguous |
| G-08 | Rollout | Shadow → 5 item → 25 item → default |

G-01 và G-02 là cổng bắt buộc trước live Gemini call. Các phase code, fake tests
và shadow infrastructure có thể triển khai trước.

## 16. Definition of Done

- Workflow đúng vòng lặp observe → navigate → detect.
- Gemini không trực tiếp điều khiển browser hoặc tự tạo URL.
- Chỉ trang được rule + detector xác nhận mới được crawl.
- Final JSON đúng schema và mọi value grounded.
- Raw HTML luôn qua BeautifulSoup; Gemini extraction/normalization chỉ nhận
  clean text/Markdown và structured draft.
- Deterministic normalization được ưu tiên.
- API key không xuất hiện trong UI, log, DB hoặc artifact.
- Retry/budget/circuit breaker được test.
- Resume không tạo model call trùng khi input hash không đổi.
- Agent trace đủ để giải thích vì sao chọn hoặc loại từng trang.
- Canary 5 và 25 item đạt metric đã chốt.
- Flow cũ có thể rollback bằng feature flag.

## 17. Tài liệu kỹ thuật tham chiếu

- Gemini function calling:
  <https://ai.google.dev/gemini-api/docs/function-calling>
- Gemini structured outputs:
  <https://ai.google.dev/gemini-api/docs/structured-output>
- Gemini API key security:
  <https://ai.google.dev/gemini-api/docs/api-key>
