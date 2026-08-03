# Hướng dẫn chạy và sử dụng AI Medical Crawler

Tài liệu này dành cho người vận hành sau khi dự án đã được cài đặt. Nếu máy
chưa có Python, thư viện hoặc Chromium, thực hiện
[INSTALLATION.md](INSTALLATION.md) trước.

## 1. Luồng chạy nhanh

Từ thư mục gốc của dự án:

```bash
cd ai-craw-data-medical
source .venv/bin/activate

PLAYWRIGHT_BROWSERS_PATH=.playwright-browsers \
  .venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
```

Mở trình duyệt tại:

```text
http://127.0.0.1:8000/
```

Giữ cửa sổ terminal chạy backend trong suốt phiên crawl. Nhấn `Ctrl+C` tại
terminal để tắt backend sau khi không còn job đang chạy.

## 2. Kiểm tra trước khi chạy

### Kiểm tra file cấu hình

Đảm bảo `.env` tồn tại:

```bash
test -f .env && echo ".env exists"
```

Các trường dưới đây có thể dùng làm cấu hình mặc định cho script kiểm thử
authenticated. Khi chạy bằng UI, username và password được nhập trực tiếp cho
từng phiên:

```dotenv
GENRE_MANUALS_BASE_URL=https://your-authorized-site.example/home.html
GENRE_MANUALS_USERNAME=your-authorized-username
GENRE_MANUALS_PASSWORD=your-authorized-password
```

Nếu sử dụng AI Agent:

```dotenv
AGENTIC_DISCOVERY_ENABLED=true
GEMINI_API_KEY=your-gemini-api-key
```

Không đưa giá trị thật của `.env` vào tài liệu, ảnh chụp, issue, log hoặc Git.

### Kiểm tra backend

Sau khi khởi động server:

```bash
curl -fsS http://127.0.0.1:8000/api/v1/health/live
curl -fsS http://127.0.0.1:8000/api/v1/health/ready
```

Ý nghĩa:

- `status: ready`: backend sẵn sàng nhận job;
- `database: ok`: SQLite và migration hoạt động;
- `artifact_store: ok`: có thể ghi output;
- `gemini_agentic: ready`: Gemini key và agentic flow đã sẵn sàng;
- `gemini_agentic: disabled`: vẫn chạy được rule-based flow, nhưng không bật
  các tùy chọn Gemini trên UI.

## 3. Khởi động trên từng hệ điều hành

### Linux/macOS

```bash
source .venv/bin/activate
PLAYWRIGHT_BROWSERS_PATH=.playwright-browsers \
  medical-crawler --host 127.0.0.1 --port 8000
```

Nếu console command chưa được nhận diện:

```bash
PLAYWRIGHT_BROWSERS_PATH=.playwright-browsers \
  .venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
```

### Windows PowerShell

```powershell
.\.venv\Scripts\Activate.ps1
$env:PLAYWRIGHT_BROWSERS_PATH=".playwright-browsers"
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

## 4. Thiết lập phiên crawl trên UI

Giao diện có hai chế độ:

1. **Crawl tự động**: hệ thống duyệt cây Medical và tìm các trang bệnh.
2. **Import tên bệnh**: hệ thống tìm đúng các bệnh được nhập hoặc import.

Các trường chung:

| Trường | Cách điền |
|---|---|
| Website cần crawl | URL HTTPS thuộc website/plugin được hỗ trợ |
| Username | Tài khoản đã được cấp quyền automation |
| Password | Password hiện tại của tài khoản |
| Xác nhận quyền | Bắt buộc đánh dấu trước khi chạy |
| Gemini Agentic Discovery | Bật khi muốn Gemini hỗ trợ chọn candidate và xác minh trang |
| AI Normalization | Bật khi muốn AI xử lý các trường còn mơ hồ sau bước làm sạch |

Password chỉ được dùng trong bộ nhớ lúc chạy và được xóa khỏi form sau khi
backend chấp nhận job. Không dùng tài khoản ngoài phạm vi được phép.

## 5. Chạy chế độ Crawl tự động

1. Chọn tab **Crawl tự động**.
2. Nhập URL, username và password.
3. Chọn **Số bệnh tối đa**, từ 1 đến 25.
4. Bật Gemini Agent nếu cần và hệ thống báo Gemini sẵn sàng.
5. Đánh dấu xác nhận quyền automation.
6. Nhấn **Thực thi crawler tự động**.

Hệ thống sẽ:

```text
đăng nhập
→ vào vùng Medical
→ quan sát và phân loại trang
→ tìm candidate
→ chỉ nhận trang được xác minh là disease detail
→ crawl nội dung và các tab
```

Chế độ này phù hợp khi cần khảo sát website hoặc thu thập một số lượng bệnh mà
không có danh sách tên từ trước.

## 6. Chạy chế độ Import tên bệnh

1. Chọn tab **Import tên bệnh**.
2. Nhập mỗi tên bệnh trên một dòng, tối đa 25 tên.
3. Hoặc chọn **Import .txt / .csv / .xlsx**.
4. Có thể chọn **Tải XLSX mẫu**, điền danh sách rồi import lại.
5. Giữ **Mở rộng menu bệnh cha** nếu một tên có thể dẫn đến danh mục chứa nhiều
   bệnh con.
6. Đánh dấu xác nhận quyền và nhấn thực thi.

Ví dụ danh sách:

```text
Angina pectoris
Atrial fibrillation
Cardiac arrhythmia
```

Quy trình tìm một tên:

```text
nhập tên vào ô “Start searching...”
→ chờ dropdown
→ thu thập toàn bộ gợi ý
→ matcher/AI đánh giá candidate
→ chọn một hoặc nhiều kết quả hợp lý
→ lưu tên đã chọn và lý do chọn
→ xác minh trang bệnh
```

Nếu kết quả không chắc chắn, hệ thống có thể giữ nhiều candidate để tránh bỏ
sót. Nếu không tìm thấy trang hợp lệ, audit ghi lại cách đã tìm và nguyên nhân
không chấp nhận kết quả.

### Mở rộng menu bệnh cha

Ví dụ `Cardiac arrhythmia` có thể dẫn tới menu cha. Khi mở rộng được bật, crawler
duyệt theo giới hạn:

- độ sâu menu tối đa: mặc định 5;
- số node tối đa: mặc định 100;
- số bệnh con tối đa: mặc định 100.

Chỉ trang được xác minh là nội dung bệnh mới đi vào bước fetch/clean/parse.
Menu cha không được xuất thành một disease JSON giả.

## 7. Theo dõi tám giai đoạn

UI hiển thị tiến độ của từng checkpoint:

| Giai đoạn | Ý nghĩa |
|---|---|
| `validate` | Kiểm tra URL, quyền và cấu hình |
| `authenticate` | Đăng nhập hoặc tái sử dụng session hợp lệ |
| `navigate` | Đi tới vùng/trang phù hợp |
| `discover` | Tìm, đánh giá và xác minh trang bệnh |
| `profile` | Quét trang đại diện và khóa contract cấu trúc nguồn |
| `fetch` | Lưu HTML, ảnh và nội dung raw của các tab |
| `clean` | BeautifulSoup/extractor làm sạch HTML và tạo Markdown |
| `parse` | Tạo structured disease JSON bằng rule parser hoặc Gemini |
| `coverage` | Đối chiếu nguồn–output; thiếu dữ liệu thì từ chối hoàn tất |
| `report` | Tổng hợp trạng thái, artifact và audit |

Không đóng tab UI hoặc tắt backend khi job đang chạy. Nếu tab UI bị reload,
giao diện cố gắng khôi phục job/report gần nhất từ backend.

Các trạng thái kết thúc:

- `completed`: tất cả item hoàn tất;
- `completed_with_errors`: một số item thành công, một số item lỗi;
- `failed`: lỗi ở cấp job, ví dụ không đăng nhập được hoặc browser không chạy.

`completed` chỉ được sử dụng khi site profile hợp lệ và mọi item đã parse đều
vượt coverage gate. Thiếu tab, table, hierarchy, related detail hoặc structured
field sẽ sinh `COVERAGE_INCOMPLETE` và chuyển job sang
`completed_with_errors`.

## 8. Hiểu kết quả chống crawl lặp

Mỗi bệnh vẫn được tải và làm sạch lại một lần để kiểm tra nội dung mới. Hệ thống
so sánh snapshot gồm nội dung chính và bốn tab:

```text
main
info
life_dd_tpd
ip
health
```

Kết quả trên UI:

- **Mới**: chưa có lần crawl thành công làm baseline;
- **Có cập nhật**: nội dung chính hoặc ít nhất một tab thay đổi;
- **Đã crawl · không đổi**: snapshot giống lần trước.

Nếu không đổi và phiên bản parser/model/schema tương thích, hệ thống tái sử
dụng disease JSON đã kiểm chứng và không gọi AI lại. HTML, screenshot và dữ
liệu tab mới vẫn được lưu làm bằng chứng cho lần kiểm tra hiện tại.

## 9. Xem và tải output

Sau khi job hoàn tất, phần **Output của phiên crawl** hiển thị:

- tổng số item;
- số thành công và lỗi;
- số nội dung mới, cập nhật và không đổi;
- trạng thái từng bệnh;
- đường dẫn audit và artifact.

Artifact thường có:

| Link | Nội dung |
|---|---|
| `HTML` | HTML gốc của trang |
| `MD` | Markdown đã làm sạch |
| `Raw` | Nội dung raw/checkpoint |
| `PNG` | Ảnh bằng chứng đã che vùng nhạy cảm |
| `4 Tabs` | Nội dung đã làm sạch của Info, Life/DD/TPD, IP, Health |
| `Tabs Raw` | Nội dung tab trước khi clean |
| `Xem nội dung` | Structured `disease.json` |

Các audit cấp job:

- **Nhật ký AI**: quyết định discovery/agent;
- **Agent trace**: dấu vết agent và model call;
- **Nhật ký import**: candidate, kết quả chọn và lý do;
- **Nhật ký menu cha-con**: node đã duyệt và provenance;
- **Report JSON**: kết quả tổng hợp của toàn job.
- **Site profile**: cấu trúc content root, tab, table, form và dấu hiệu dynamic;
- **Coverage**: đối chiếu từng thành phần nguồn với output của từng item.

File vật lý được lưu tại:

```text
output/jobs/{job_id}/
├── report.json
├── site-profile.json
├── coverage-report.json
├── import-search.json
├── category-expansion.json
└── items/{disease}--{item_id}/
    ├── manifest.json
    ├── raw.html
    ├── screenshot.png
    ├── content.html
    ├── markdown.md
    ├── tabs-raw.json
    ├── tabs.json
    ├── disease.json
    └── coverage.json
```

Một số file audit chỉ tồn tại khi chế độ tương ứng được sử dụng.

## 10. Chạy lại sau khi cập nhật code

Không chạy `git pull` khi job đang hoạt động. Sau khi job kết thúc:

```bash
git pull origin main
source .venv/bin/activate
python -m pip install -e ".[dev]"
PLAYWRIGHT_BROWSERS_PATH=.playwright-browsers \
  .venv/bin/playwright install chromium
```

Khởi động lại backend. Migration SQLite mới được áp dụng tự động và các
checkpoint cũ vẫn được giữ.

## 11. Dừng hệ thống an toàn

1. Chờ job hiện tại đạt trạng thái kết thúc.
2. Đảm bảo report đã hiển thị.
3. Quay lại terminal chạy Uvicorn.
4. Nhấn `Ctrl+C`.
5. Chờ thông báo `Application shutdown complete`.

Không xóa `state/` hoặc `output/` nếu còn cần resume, audit hoặc so sánh
incremental crawl.

## 12. Xử lý lỗi thường gặp

### `BROWSER_UNAVAILABLE`

```bash
PLAYWRIGHT_BROWSERS_PATH=.playwright-browsers \
  .venv/bin/playwright install chromium
```

Sau đó khởi động backend với cùng biến `PLAYWRIGHT_BROWSERS_PATH`.

### Không đăng nhập được

Kiểm tra:

- URL website;
- username/password;
- tài khoản có bị khóa hoặc hết hạn;
- CAPTCHA/MFA có đang yêu cầu thao tác thủ công;
- session cũ trong `state/sessions/` có còn hợp lệ.

Crawler không tự động vượt CAPTCHA hoặc MFA.

### `GROUNDING_FAILED`

Structured output của AI không được chứng minh bằng nội dung nguồn. Hệ thống có
thể thử repair một lần; nếu vẫn lỗi, item được giữ ở trạng thái lỗi để kiểm tra
HTML, Markdown và tab raw.

### Có warning `missing_field:*`

Nguồn hoặc parser chưa tìm được trường tương ứng, ví dụ `risk_factors` hoặc
`prevention`. Đây là cảnh báo thiếu dữ liệu, không đồng nghĩa toàn bộ disease
JSON bị hỏng.

### `ai_normalization_not_required`

BeautifulSoup và normalization xác định không có trường mơ hồ cần gọi AI. Đây
là thông báo tối ưu, không phải lỗi.

### Job `completed_with_errors`

Mở từng item lỗi và xem:

1. `last_error_code`;
2. raw HTML và PNG;
3. Markdown;
4. tab raw/tab clean;
5. import/category/agent audit.

Các item thành công vẫn sử dụng và tải xuống bình thường.

### Port 8000 đã được sử dụng

Tìm process đang chạy hoặc dùng cổng khác:

```bash
.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8001
```

Sau đó mở `http://127.0.0.1:8001/`.

## 13. Checklist cho một phiên crawl

### Trước khi chạy

- [ ] Backend và health endpoint đang `ready`.
- [ ] Chromium được tìm thấy.
- [ ] Tài khoản thuộc phạm vi được phép automation.
- [ ] Gemini sẵn sàng nếu bật AI Agent.
- [ ] Danh sách import không quá 25 tên.
- [ ] Còn đủ dung lượng cho HTML, JSON và PNG.

### Sau khi chạy

- [ ] Job đạt `completed` hoặc đã hiểu các lỗi thành phần.
- [ ] Report JSON đã được tạo.
- [ ] Các disease cần thiết có đủ artifact.
- [ ] Đã xem badge mới/cập nhật/không đổi.
- [ ] Đã kiểm tra warning và audit của item lỗi.
- [ ] Không chia sẻ `.env`, session, raw output nhạy cảm ra ngoài phạm vi cho
  phép.
