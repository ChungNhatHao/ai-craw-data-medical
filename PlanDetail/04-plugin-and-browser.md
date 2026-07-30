# 04 — Plugin and Browser

## 1. Plugin contract

```python
class SitePlugin(ABC):
    name: str
    allowed_domains: set[str]

    async def login(self, page: Page, credentials: Credentials) -> None: ...
    async def validate_session(self, page: Page) -> bool: ...
    async def discover(self, page: Page) -> AsyncIterator[DiscoveredItem]: ...
    async def open_item(self, page: Page, item: DiscoveredItem) -> None: ...
    async def classify_page(self, page: Page) -> PageClassification: ...
    async def find_next_content_candidate(
        self, page: Page, visited: set[str]
    ) -> NavigationCandidate | None: ...
    async def dismiss_known_popups(self, page: Page) -> int: ...
    async def locate_content_root(self, page: Page) -> Locator: ...
    def canonicalize_url(self, url: str) -> str: ...
    def clean_content(self, html: str) -> str: ...
    def metadata_from_page(self, html: str) -> dict: ...
```

Optional capabilities:

```python
supports_pagination: bool
supports_incremental_headers: bool
custom_parser: StructuredParser | None
vision_policy: VisionPolicy
```

Registry fail-fast nếu trùng plugin name hoặc plugin thiếu capability bắt buộc.

Page classification contract:

```python
class PageType(StrEnum):
    DISEASE_DETAIL = "disease_detail"
    DISEASE_LIST = "disease_list"
    HOME_OR_MENU = "home_or_menu"
    LOGIN = "login"
    BLOCKED_OR_CAPTCHA = "blocked_or_captcha"
    UNKNOWN = "unknown"

class PageClassification(BaseModel):
    page_type: PageType
    confidence: float
    matched_signals: list[str]
    fingerprint: str
```

## 2. `genre_manuals` plugin

Phân rã:

- `selectors.py`: selector có tên, primary và fallback.
- `login.py`: form login, detect success/error.
- `navigator.py`: disease menu, pagination, detail links.
- `plugin.py`: implement contract và compose module.
- `parser.py`: rule riêng để nhận heading/metadata.
- `prompts/`: chỉ chứa prompt cần kiến thức layout của site.

Selector không rải trong orchestration code. Ví dụ:

```python
LOGIN_EMAIL = SelectorSet(
    primary='input[name="email"]',
    fallbacks=('input[type="email"]',),
)
```

Selector thực tế phải được xác nhận từ fixture/site; tài liệu này không đoán DOM.

## 3. Login/session

Luồng:

1. Mở login URL trong allowed domain.
2. Chờ DOM ready.
3. Dismiss popup đã biết.
4. Điền credential từ secret provider.
5. Submit và chờ một trong: success marker, error marker, timeout.
6. Validate bằng authenticated marker hoặc protected endpoint.
7. Lưu Playwright `storage_state` atomic.
8. Redact cookie/token khỏi log.

Không coi URL redirect là bằng chứng duy nhất của login thành công.

Cookie:

- Đường dẫn mặc định `state/sessions/{plugin}.json`.
- Không nằm trong output public.
- Permission hạn chế ở host.
- Invalid/expired state được thay thế sau login thành công.
- Không chụp screenshot khi password đang hiển thị trong form.

## 4. Discovery

Discovery phải:

- Chỉ yield URL thuộc allowed domain.
- Chuẩn hóa URL trước khi deduplicate.
- Xử lý pagination/load-more/infinite scroll có giới hạn.
- Dừng khi trang không sinh item mới.
- Lưu title hint và discovery page.
- Có max pages/max items từ config để chống loop.

Điều kiện kết thúc:

```text
next button disabled
OR no new canonical URL after N rounds
OR max_pages/max_items reached
```

Nếu đạt safety limit, job report warning thay vì coi là full success.

## 5. Disease page detection loop

Sau mỗi click hoặc `goto`, plugin phải classify trang hiện tại trước khi core
cho phép crawl:

1. Dismiss popup đã biết.
2. Kiểm tra domain, HTTP state và session.
3. Thu thập URL, breadcrumb, heading, content root, section marker và link density.
4. Trả `PageClassification`.
5. Nếu là `DISEASE_DETAIL`, xác nhận title/content root rồi chuyển sang fetch.
6. Nếu là list/menu, tìm candidate chưa visited và navigation lại.
7. Nếu `UNKNOWN`, thử locator/recovery khác; Vision chỉ là fallback cuối.
8. Nếu login, refresh session; nếu blocked/CAPTCHA, pause.
9. Dừng khi đạt max hops, repeated fingerprint hoặc no-progress threshold.

Plugin không tự chạy vòng lặp vô hạn; core LangGraph sở hữu counter và quyết
định route. Plugin chỉ classify trang và cung cấp candidate/action tiếp theo.

### Tiêu chí `DISEASE_DETAIL`

Yêu cầu tối thiểu:

- URL thuộc allowed domain.
- Không có login/block/error marker.
- Có đúng một disease title/heading hợp lệ.
- Có content root với độ dài tối thiểu.
- Có ít nhất một section/content signal y khoa.
- Tổng score đạt threshold, đề xuất `0.80`.

URL pattern đơn lẻ hoặc heading đơn lẻ không đủ để cho phép crawl.

## 6. Fetch detail

1. Nhận trang đã được classifier xác nhận `DISEASE_DETAIL`.
2. Chờ content marker, không dựa duy nhất vào `networkidle`.
3. Dismiss popup và classify lại nếu DOM thay đổi đáng kể.
4. Validate URL/domain/session.
5. Chờ lazy content bằng selector/plugin hook.
6. Capture HTML.
7. Capture full-page screenshot nếu config bật.
8. Kiểm tra content root không rỗng.

Navigation timeout, selector timeout và total item timeout là ba config riêng.

## 7. Locator strategy

Thứ tự:

1. `data-testid`/stable attribute nếu site có.
2. ARIA role + accessible name.
3. Label/text ổn định.
4. CSS selector scoped trong container.
5. DOM heuristic.
6. Vision fallback.

Mọi selector có:

- Tên semantic.
- Primary.
- Fallback list.
- Expected cardinality.
- Timeout.

Nếu locator trả nhiều element ngoài dự kiến, fail ambiguous; không click phần tử
đầu tiên một cách im lặng.

## 8. Popup

Popup handler chỉ đóng pattern allowlist:

- Cookie consent.
- Newsletter/modal.
- Chat widget overlay.
- Known announcement.

Không click nút có tác dụng chấp nhận điều khoản, mua hàng, xóa dữ liệu hoặc thay
đổi account ngoài hành động đã phê duyệt.

Sau khi click close:

- Xác nhận overlay biến mất.
- Giới hạn số lần xử lý.
- Ghi popup type vào structured log.

## 9. Vision fallback

Chỉ kích hoạt khi:

- Page load hợp lệ.
- Session còn hiệu lực.
- Không có CAPTCHA/block.
- Primary/fallback/heuristic locator đều thất bại.
- Budget cho job chưa vượt giới hạn.

Input:

- Screenshot đã che vùng nhạy cảm.
- Mô tả hành động cụ thể.
- Kích thước viewport.
- Danh sách action được phép.

Output schema:

```json
{
  "action": "click|scroll|none",
  "target": "semantic description",
  "coordinates": {"x": 0, "y": 0},
  "confidence": 0.0,
  "reason_code": "TARGET_FOUND|TARGET_NOT_FOUND|AMBIGUOUS"
}
```

Guardrail:

- Chỉ `click`/`scroll` trong MVP.
- Confidence tối thiểu cấu hình, đề xuất `0.85`.
- Coordinates phải nằm trong viewport và ngoài vùng cấm.
- Tối đa 2 Vision actions/item.
- Chụp screenshot sau action và validate kết quả bằng DOM.
- Không dùng Vision để nhập credential hoặc xử lý CAPTCHA.

## 10. HTML extraction và Markdown

Plugin cung cấp content root tốt nhất. Generic fallback:

1. Xóa `script`, `style`, `noscript`, navigation, footer và form.
2. Giữ heading, paragraph, list, table, emphasis, link.
3. Dùng Trafilatura nếu content root không xác định.
4. So sánh minimum text length và heading presence.
5. Chuẩn hóa HTML rồi convert Markdown.

Không silently drop table; table khó chuyển phải giữ HTML fragment trong
Markdown hoặc thêm warning.

## 11. Structured parsing prompt

Prompt contract:

- Chỉ dùng nội dung được cung cấp.
- Không bổ sung kiến thức y khoa.
- Preserve qualifiers, negation và dosage nếu nguồn có.
- Không hợp nhất section không chắc chắn.
- Trả đúng JSON schema.
- Field thiếu trả `null`/`[]`.
- Tạo warning khi nội dung mâu thuẫn hoặc không phân loại được.

Nội dung dài được chunk theo heading, parse từng chunk, sau đó merge bằng rule
xác định. Không cắt theo token ở giữa câu nếu có thể tránh.

## 12. Prompt modules và điều kiện gọi

Prompt không thay thế code điều phối. Mỗi prompt có version trong front matter,
input/output schema và test fixture.

| Prompt | Khi gọi | Input chính | Output |
|---|---|---|---|
| `login_prompt.md` | Chỉ hỗ trợ nhận diện trạng thái login khó xác định; không nhập credential | screenshot/DOM đã redact | `LOGIN_FORM`, `LOGGED_IN`, `ERROR`, `UNKNOWN` |
| `navigation_prompt.md` | Locator menu deterministic thất bại | screenshot + target semantic | Vision action schema |
| `discovery_prompt.md` | Cần phân biệt link disease với link điều hướng mơ hồ | danh sách link/text đã lọc | danh sách candidate + confidence |
| `extraction_prompt.md` | Section không map được bằng heading rules | Markdown section | semantic section label |
| `parser_prompt.md` | Chuyển Markdown sạch thành disease schema | chunk + schema | JSON fragment hợp lệ |
| `recovery_prompt.md` | Lỗi UI không thuộc pattern đã biết và policy cho phép | evidence đã redact + error context | action allowlist hoặc `none` |

Quy tắc chung:

- Không gửi cookie, credential, hidden form field hoặc header bí mật.
- `login_prompt` không được trả tọa độ/giá trị để điền password.
- `discovery_prompt` không được tự tạo URL; candidate URL phải có trong input.
- `parser_prompt` không được dùng kiến thức ngoài nội dung nguồn.
- `recovery_prompt` chỉ đề xuất action; code vẫn kiểm tra allowlist và hậu điều
  kiện trước khi tiếp tục.
- Prompt thay đổi behavior phải tăng version và chạy regression fixtures.
