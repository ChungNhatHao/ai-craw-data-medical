# 01 — Scope and Architecture

## 1. Mục tiêu sản phẩm

Hệ thống nhận một site plugin và crawl job, tự đăng nhập, phát hiện danh sách
bệnh, tải trang chi tiết, chuyển nội dung sang Markdown và JSON có cấu trúc,
sau đó xuất report.

### Use case chính

1. Operator kiểm tra hoặc tạo browser session.
2. Operator tạo crawl job cho plugin `genre_manuals`.
3. Engine discover danh sách bệnh.
4. Engine xử lý từng bệnh và checkpoint.
5. Job có thể bị dừng và resume.
6. Operator xem report, retry item lỗi và export kết quả.

### Ngoài phạm vi

- Suy luận/chẩn đoán y khoa.
- Trả lời câu hỏi người dùng.
- Enrichment từ nguồn bên ngoài.
- Vector hóa hoặc lập chỉ mục RAG.
- Phân tán worker trên nhiều máy trong MVP/V2.
- Vượt CAPTCHA, bypass access control hoặc né rate limit.

## 2. Kiến trúc logic

```text
┌────────────┐       ┌─────────────────┐
│ FastAPI/CLI│──────▶│ Job Service     │
└────────────┘       └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │ LangGraph       │
                    │ Orchestrator    │
                    └───┬────┬────┬───┘
                        │    │    │
          ┌─────────────┘    │    └──────────────┐
          ▼                  ▼                   ▼
┌────────────────┐  ┌────────────────┐  ┌────────────────┐
│ Site Plugin    │  │ Parse Pipeline │  │ State/Artifact │
│ + Playwright   │  │ clean/LLM      │  │ SQLite/files   │
└────────────────┘  └────────────────┘  └────────────────┘
```

### Trách nhiệm component

| Component | Trách nhiệm | Không chịu trách nhiệm |
|---|---|---|
| API/CLI | nhận lệnh, validate input, trả trạng thái | crawl trực tiếp trong request |
| Job Service | tạo/cancel/resume job, query report | selector website |
| Orchestrator | điều phối state và nhánh lỗi | parse DOM chi tiết |
| Browser Manager | lifecycle browser/context/page | logic theo website |
| Site Plugin | login, discover, selector, content root | lưu job/checkpoint |
| Parse Pipeline | clean, Markdown, JSON, validation | navigation |
| Repository | transaction và state bền vững | business decision |
| Artifact Store | ghi/đọc file atomic | quyết định item state |

## 3. Luồng dữ liệu

```text
URL
 → Playwright response/page
 → raw.html + screenshot.png
 → content.html
 → markdown.md
 → structured parser
 → disease.json
 → manifest.json
```

Mỗi bước đọc artifact của bước trước. Nếu parse lỗi, hệ thống có thể chạy lại từ
`markdown.md`; nếu clean lỗi, chạy lại từ `raw.html`; chỉ fetch lại khi nguồn
artifact bị thiếu/hỏng hoặc operator yêu cầu refresh.

## 4. Cấu trúc source code đề xuất

```text
medical-crawler/
├── app/
│   ├── api/
│   │   ├── routes_health.py
│   │   ├── routes_jobs.py
│   │   └── schemas.py
│   ├── agents/
│   │   ├── graph.py
│   │   ├── nodes.py
│   │   ├── routing.py
│   │   └── state.py
│   ├── browser/
│   │   ├── manager.py
│   │   ├── session.py
│   │   ├── actions.py
│   │   └── screenshots.py
│   ├── core/
│   │   ├── config.py
│   │   ├── errors.py
│   │   ├── ids.py
│   │   └── lifecycle.py
│   ├── models/
│   │   ├── crawl.py
│   │   ├── disease.py
│   │   └── report.py
│   ├── parser/
│   │   ├── extractor.py
│   │   ├── cleaner.py
│   │   ├── markdown.py
│   │   ├── structured.py
│   │   └── validator.py
│   ├── plugins/
│   │   ├── base.py
│   │   ├── registry.py
│   │   └── genre_manuals/
│   │       ├── plugin.py
│   │       ├── login.py
│   │       ├── navigator.py
│   │       ├── selectors.py
│   │       ├── parser.py
│   │       └── prompts/
│   ├── prompts/
│   │   ├── extraction_prompt.md
│   │   ├── parser_prompt.md
│   │   └── recovery_prompt.md
│   ├── repositories/
│   │   ├── database.py
│   │   ├── jobs.py
│   │   ├── items.py
│   │   └── attempts.py
│   ├── services/
│   │   ├── jobs.py
│   │   ├── crawl.py
│   │   ├── export.py
│   │   └── reports.py
│   ├── storage/
│   │   ├── artifacts.py
│   │   └── hashing.py
│   └── utils/
│       ├── logging.py
│       ├── retry.py
│       └── time.py
├── migrations/
├── output/
├── state/
├── logs/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── e2e/
│   └── fixtures/
├── main.py
├── pyproject.toml
├── Dockerfile
└── docker-compose.yml
```

## 5. Ranh giới dependency

- `core`, `models` không import FastAPI, Playwright hoặc plugin cụ thể.
- `plugins` phụ thuộc interface core, không phụ thuộc API.
- `agents` gọi service/interface, không thao tác trực tiếp SQLite.
- `parser` nhận string/model và trả model; không biết job lifecycle.
- `api` không import implementation của `genre_manuals`.
- Plugin được nạp qua registry bằng tên cấu hình.

## 6. Quy tắc async và tài nguyên

- Toàn bộ browser I/O và orchestration dùng `async`.
- Không dùng một Playwright `Page` đồng thời cho nhiều item.
- Một job sở hữu browser context; context đóng trong `finally`.
- SQLite write được serialize qua repository/transaction.
- CPU-heavy cleaning có thể chuyển sang thread khi profiling chứng minh cần.
- API tạo background job và trả ngay; không giữ HTTP request đến khi crawl xong.

## 7. Môi trường

| Environment | Mục đích | Dữ liệu |
|---|---|---|
| local | phát triển với fixture | fake/test |
| staging | smoke test website thật | giới hạn 1–3 item |
| production | full crawl được phê duyệt | dữ liệu thật |

Selector và plugin code giống nhau giữa các môi trường; credential, giới hạn và
output path đi qua config.
