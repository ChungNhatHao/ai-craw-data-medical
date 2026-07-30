# Hướng dẫn cài đặt AI Medical Crawler

Tài liệu này mô tả các phần mềm hệ thống, thư viện Python, browser runtime và
cấu hình cần thiết để cài đặt và chạy dự án trên máy mới.

Sau khi cài đặt xong, sử dụng [RUN_GUIDE.md](RUN_GUIDE.md) để khởi động và vận
hành crawler.

## 1. Thành phần bắt buộc

| Thành phần | Phiên bản/đề xuất | Mục đích |
|---|---|---|
| Git | Bản ổn định hiện hành | Clone và cập nhật mã nguồn |
| Python | `3.12.x` | Runtime của backend; dự án không hỗ trợ Python 3.11 hoặc 3.13 |
| `pip` và `venv` | Đi kèm Python 3.12 | Tạo môi trường Python độc lập |
| Playwright Chromium | Playwright tự quản lý | Đăng nhập, điều hướng và crawl website thật |
| SQLite | Đi kèm Python | Lưu job, checkpoint, audit và lịch sử crawl |
| Kết nối Internet | Bắt buộc khi cài và crawl | Tải thư viện, Chromium, gọi Gemini và truy cập website |

Các thành phần tùy chọn:

- `curl`: kiểm tra health endpoint và chạy smoke test;
- Gemini API key: bắt buộc nếu bật Navigation/Disease/Normalization Agent;
- trình biên dịch C và thư viện hệ thống: chỉ cần nếu `pip` không tìm thấy
  binary wheel phù hợp cho `lxml`.

## 2. Cài phần mềm hệ thống

### Ubuntu/Debian

```bash
sudo apt update
sudo apt install -y git curl python3.12 python3.12-venv python3-pip
```

Nếu bản phân phối không cung cấp Python 3.12 trong repository mặc định, hãy cài
Python 3.12 bằng repository chính thức của hệ điều hành, `pyenv`, hoặc công cụ
quản lý Python được tổ chức phê duyệt.

Playwright có thể tự cài các thư viện Linux cần cho Chromium:

```bash
.venv/bin/playwright install --with-deps chromium
```

Lệnh này có thể yêu cầu quyền `sudo`. Trên server không cho phép cài system
package, quản trị viên cần chuẩn bị các dependency Chromium trước.

### Windows

1. Cài Git for Windows.
2. Cài Python 3.12 từ python.org và bật tùy chọn **Add Python to PATH**.
3. Chạy các lệnh trong PowerShell.

Kích hoạt virtual environment trên Windows:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
playwright install chromium
```

### macOS

Cài Git và Python 3.12 bằng Homebrew hoặc trình cài chính thức:

```bash
brew install git python@3.12
```

Sau đó thực hiện các bước cài dự án ở phần tiếp theo.

## 3. Clone và tạo môi trường dự án

```bash
git clone git@github.com:ChungNhatHao/ai-craw-data-medical.git
cd ai-craw-data-medical

python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Nếu máy chưa cấu hình SSH cho GitHub, có thể clone bằng HTTPS:

```bash
git clone https://github.com/ChungNhatHao/ai-craw-data-medical.git
```

`.[dev]` cài cả thư viện chạy thật và công cụ kiểm thử. Trên máy production chỉ
cần runtime dependencies:

```bash
python -m pip install -e .
```

## 4. Các thư viện Python được cài

### Runtime dependencies

| Thư viện | Khoảng phiên bản | Vai trò |
|---|---:|---|
| `beautifulsoup4` | `>=4.12,<5` | Phân tích và làm sạch HTML trước khi đưa cho agent |
| `fastapi` | `>=0.115,<1` | REST API và web operator console |
| `google-genai` | `>=1.0,<2` | Kết nối Gemini API |
| `langgraph` | `>=0.2,<1` | Điều phối flow và trạng thái agent |
| `loguru` | `>=0.7,<1` | Logging có cấu trúc |
| `lxml` | `>=5,<7` | HTML/XML parser hiệu năng cao |
| `playwright` | `>=1.49,<2` | Browser automation |
| `pydantic` | `>=2.10,<3` | Kiểm tra schema request, artifact và disease JSON |
| `pydantic-settings` | `>=2.7,<3` | Đọc và kiểm tra cấu hình `.env` |
| `python-dotenv` | `>=1,<2` | Nạp biến môi trường cục bộ |
| `trafilatura` | `>=2,<3` | Content extractor dự phòng |
| `uvicorn[standard]` | `>=0.34,<1` | Chạy FastAPI server |

### Development dependencies

| Thư viện | Vai trò |
|---|---|
| `httpx` | Test API và HTTP client cho kiểm thử |
| `pytest` | Unit/integration test |
| `ruff` | Lint và kiểm tra import/style |
| `mypy` | Kiểm tra kiểu dữ liệu ở chế độ strict |

Phiên bản chính xác đã được khóa trong `uv.lock`. Không cần cài riêng
`openpyxl`: chức năng import/export XLSX hiện tại xử lý định dạng cần thiết bằng
module chuẩn và logic nội bộ của dự án.

## 5. Cài Chromium cho Playwright

### Cài trong cache mặc định

```bash
playwright install chromium
```

### Cài bên trong thư mục dự án

Cách này dễ sao lưu và tránh lỗi `BROWSER_UNAVAILABLE` do backend không tìm
thấy Chromium:

```bash
PLAYWRIGHT_BROWSERS_PATH=.playwright-browsers \
  .venv/bin/playwright install chromium
```

Khi chạy backend, sử dụng lại đúng đường dẫn:

```bash
PLAYWRIGHT_BROWSERS_PATH=.playwright-browsers \
  .venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
```

Nếu gặp lỗi:

```text
BROWSER_UNAVAILABLE
Không tìm thấy Chromium runtime
```

hãy kiểm tra:

```bash
PLAYWRIGHT_BROWSERS_PATH=.playwright-browsers \
  .venv/bin/playwright install chromium

ls -la .playwright-browsers
```

## 6. Tạo và cấu hình `.env`

```bash
cp .env.example .env
```

Điền các trường bí mật chỉ trong `.env`:

```dotenv
GENRE_MANUALS_BASE_URL=https://example-authorized-site.test/home.html
GENRE_MANUALS_USERNAME=your-authorized-username
GENRE_MANUALS_PASSWORD=your-authorized-password

AGENTIC_DISCOVERY_ENABLED=true
AI_NORMALIZATION_ENABLED=true
GEMINI_API_KEY=your-gemini-api-key
```

Không đưa `.env`, API key, password, database, browser session hoặc output crawl
lên Git. `.gitignore` của dự án đã loại trừ các file này.

Gemini là tùy chọn:

- để `AGENTIC_DISCOVERY_ENABLED=false` nếu chỉ chạy rule-based flow;
- cần `GEMINI_API_KEY` hợp lệ khi bật agentic discovery/extraction;
- có thể để `AI_NORMALIZATION_ENABLED=false` nếu không cần AI normalization.

## 7. Thư mục runtime

Backend tự tạo các thư mục cần thiết:

```text
state/          SQLite database và browser session
output/         HTML, Markdown, JSON, PNG và report của từng job
logs/           Log runtime
```

Database migration trong `migrations/` được chạy tự động khi ứng dụng khởi
động. Không cần tạo bảng SQLite thủ công.

Các thư mục runtime phải cho phép user chạy backend đọc và ghi:

```bash
mkdir -p state output logs
```

## 8. Khởi động hệ thống

Kích hoạt virtual environment:

```bash
source .venv/bin/activate
```

Chạy bằng console command:

```bash
medical-crawler --host 127.0.0.1 --port 8000
```

Hoặc chạy trực tiếp bằng Uvicorn:

```bash
PLAYWRIGHT_BROWSERS_PATH=.playwright-browsers \
  .venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
```

Mở giao diện:

```text
http://127.0.0.1:8000/
```

Không bind `0.0.0.0` hoặc mở cổng ra Internet khi chưa bổ sung authentication,
HTTPS và access control cho API.

## 9. Kiểm tra sau cài đặt

### Health check

```bash
curl -fsS http://127.0.0.1:8000/api/v1/health/live
curl -fsS http://127.0.0.1:8000/api/v1/health/ready
```

Kết quả readiness mong đợi:

```json
{
  "status": "ready",
  "database": "ok",
  "artifact_store": "ok",
  "gemini_agentic": "ready"
}
```

Nếu không bật Gemini, `gemini_agentic` có thể là `disabled`; browser và
rule-based flow vẫn có thể chạy.

### Browser smoke test

```bash
PLAYWRIGHT_BROWSERS_PATH=.playwright-browsers \
  .venv/bin/python -m app.browser.smoke
```

### Quality gates

```bash
.venv/bin/ruff check app tests
.venv/bin/mypy app
.venv/bin/pytest
```

## 10. Cài đặt bằng `uv` (tùy chọn)

Nếu máy đã cài `uv`, có thể dùng lock file để tạo môi trường nhất quán:

```bash
uv sync --extra dev
source .venv/bin/activate
PLAYWRIGHT_BROWSERS_PATH=.playwright-browsers \
  uv run playwright install chromium
```

Không cần dùng đồng thời cả `pip install -e ".[dev]"` và `uv sync`; chọn một
phương thức quản lý môi trường.

## 11. Lỗi cài đặt thường gặp

### Sai phiên bản Python

```text
requires-python >=3.12,<3.13
```

Khắc phục: tạo lại `.venv` bằng Python 3.12.

### Thiếu module Python

```text
ModuleNotFoundError
```

Khắc phục:

```bash
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

### Chromium mở không được trên Linux

Khắc phục:

```bash
.venv/bin/playwright install --with-deps chromium
```

Sau đó chạy lại với cùng `PLAYWRIGHT_BROWSERS_PATH` đã dùng khi cài.

### Gemini báo chưa sẵn sàng

Kiểm tra:

- `.env` có `GEMINI_API_KEY`;
- `AGENTIC_DISCOVERY_ENABLED=true`;
- API key còn hiệu lực và có quyền gọi model được cấu hình;
- máy có thể kết nối tới Gemini API.

### Không ghi được database hoặc artifact

Đảm bảo user chạy backend có quyền ghi vào `state/`, `output/` và `logs/`.

## 12. Checklist bàn giao máy mới

- [ ] Git đã cài và clone được repository.
- [ ] Python đúng phiên bản 3.12.
- [ ] `.venv` đã tạo và dependencies đã cài.
- [ ] Chromium đã cài thành công.
- [ ] `.env` đã tạo nhưng không được commit.
- [ ] Tài khoản website thuộc phạm vi được phép crawl.
- [ ] Gemini key đã cấu hình nếu sử dụng AI Agent.
- [ ] `health/live` và `health/ready` trả kết quả hợp lệ.
- [ ] Browser smoke test chạy thành công.
- [ ] Ruff, Mypy và Pytest đều vượt qua.
- [ ] API chỉ được mở trong mạng nội bộ an toàn.
