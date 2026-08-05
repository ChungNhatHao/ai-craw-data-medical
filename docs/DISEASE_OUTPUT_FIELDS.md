# Định nghĩa các field của `disease.json`

Tài liệu này mô tả cấu trúc output chuẩn `disease.json` schema `1.2`. File tham chiếu:
`output/jobs/ffb80fbb-2ec0-4db0-9496-8aab3a17cc06/items/alzheimer-s-disease--4490f0a7e03d/disease.json`.

## Quy ước

- `string`: chuỗi ký tự.
- `integer`: số nguyên.
- `number`: số thực hoặc số nguyên.
- `boolean`: `true` hoặc `false`.
- `object`: JSON object.
- `array<T>`: mảng các phần tử kiểu `T`.
- `null`: không có giá trị. `T | null` nghĩa là field nhận kiểu `T` hoặc `null`.
- SHA-256 là chuỗi 64 ký tự hệ thập lục phân viết thường, khớp `^[0-9a-f]{64}$`.
- Các mảng không có dữ liệu thường được xuất thành `[]`; chuỗi nội dung tab không có dữ liệu thường là `""`.

## 1. Cấu trúc cấp cao nhất

| JSON path | Kiểu | Bắt buộc | Ý nghĩa |
| --- | --- | --- | --- |
| `schema_version` | `string` | Có | Phiên bản schema của tài liệu. Giá trị hiện tại là `1.2`. |
| `document_id` | `string` (SHA-256) | Có | ID duy nhất của crawl item; trong luồng hiện tại chính là `item_id`. |
| `source` | `object` | Có | Nguồn và provenance của nội dung đã crawl. |
| `disease` | `object` | Có | Dữ liệu y khoa có cấu trúc được trích xuất. |
| `menu_hierarchy` | `array<object>` | Không | Đường dẫn phân cấp từ menu gốc đến trang bệnh hiện tại. Mặc định `[]`. |
| `sections` | `array<object>` | Có | Các section nội dung đã làm sạch, theo thứ tự xuất hiện. |
| `tabs` | `array<object>` | Không | Nội dung sạch của các tab Info, Life/DD/TPD, IP và Health. Mặc định `[]`. |
| `parse_metadata` | `object` | Có | Metadata của quá trình parse/trích xuất dữ liệu. |

## 2. `source` — nguồn dữ liệu

| JSON path | Kiểu | Bắt buộc | Ý nghĩa / ràng buộc |
| --- | --- | --- | --- |
| `source.plugin` | `string` | Có | Tên plugin crawler đã xử lý nguồn, ví dụ `genre_manuals`; không được rỗng. |
| `source.url` | `string` (URL) | Có | URL thực tế được truy cập. |
| `source.canonical_url` | `string` (URL) | Có | URL chuẩn dùng để định danh và chống trùng tài liệu. |
| `source.retrieved_at` | `string` (date-time) | Có | Thời điểm lấy dữ liệu, theo ISO 8601, ví dụ `2026-08-03T04:48:01.169308Z`. |
| `source.content_hash` | `string` (SHA-256) | Có | Hash của nội dung nguồn dùng để kiểm tra thay đổi và tái sử dụng artifact. |
| `source.language` | `string` | Có | Mã ngôn ngữ của nội dung nguồn, dài từ 2 đến 16 ký tự, ví dụ `en`. |

## 3. `disease` — dữ liệu bệnh

| JSON path | Kiểu | Bắt buộc | Ý nghĩa |
| --- | --- | --- | --- |
| `disease.name` | `string` | Có | Tên chính của bệnh; không được rỗng. |
| `disease.aliases` | `array<string>` | Không | Tên khác, tên đồng nghĩa hoặc cách gọi liên quan. Mặc định `[]`. |
| `disease.summary` | `string hoặc null` | Không | Mô tả/tóm tắt tổng quan về bệnh. |
| `disease.causes` | `array<string>` | Không | Các nguyên nhân gây bệnh được nêu trong nguồn. Mặc định `[]`. |
| `disease.risk_factors` | `array<string>` | Không | Các yếu tố nguy cơ. Mặc định `[]`. |
| `disease.symptoms` | `array<string>` | Không | Triệu chứng hoặc biểu hiện lâm sàng. Mặc định `[]`. |
| `disease.diagnosis` | `array<string>` | Không | Phương pháp/chứng cứ hỗ trợ chẩn đoán. Mặc định `[]`. |
| `disease.treatment` | `array<string>` | Không | Phương pháp điều trị hoặc quản lý bệnh. Mặc định `[]`. |
| `disease.prevention` | `array<string>` | Không | Biện pháp phòng ngừa. Mặc định `[]`. |
| `disease.prognosis` | `string hoặc null` | Không | Tiên lượng và diễn tiến dự kiến của bệnh. |
| `disease.when_to_seek_care` | `array<string>` | Không | Dấu hiệu hoặc tình huống cần tìm trợ giúp y tế. Mặc định `[]`. |

`[]` hoặc `null` biểu thị nguồn không cung cấp dữ liệu cho field tương ứng; không nên tự suy diễn để điền giá trị.

## 4. `menu_hierarchy[]` — phân cấp menu

| JSON path | Kiểu | Bắt buộc | Ý nghĩa / ràng buộc |
| --- | --- | --- | --- |
| `menu_hierarchy[].level` | `integer` | Có | Độ sâu của node, bắt đầu từ `0`; các level phải liên tục theo vị trí trong mảng. |
| `menu_hierarchy[].distance_from_disease` | `integer` | Có | Số bước từ node này đến trang bệnh; node hiện tại có giá trị `0`. |
| `menu_hierarchy[].label` | `string` | Có | Nhãn hiển thị của menu, dài từ 1 đến 1.000 ký tự. |
| `menu_hierarchy[].url` | `string (URL) hoặc null` | Không | URL của node menu nếu lấy được. |
| `menu_hierarchy[].is_current` | `boolean` | Không | `true` nếu là trang bệnh hiện tại. Chỉ phần tử cuối được là `true`; mặc định `false`. |

Với mảng có `N` phần tử, phần tử ở vị trí `i` phải có `level = i` và
`distance_from_disease = N - 1 - i`.

## 5. `sections[]` — section nội dung

| JSON path | Kiểu | Bắt buộc | Ý nghĩa / ràng buộc |
| --- | --- | --- | --- |
| `sections[].heading` | `string` | Có | Tiêu đề section; không được rỗng. |
| `sections[].level` | `integer` | Có | Cấp heading Markdown, từ `1` đến `6`. |
| `sections[].order` | `integer` | Có | Thứ tự section trong tài liệu, bắt đầu từ `1`. |
| `sections[].markdown` | `string` | Có | Toàn bộ section ở dạng Markdown đã làm sạch; không được rỗng. |

## 6. `tabs[]` — nội dung từng tab

| JSON path | Kiểu | Bắt buộc | Ý nghĩa / ràng buộc |
| --- | --- | --- | --- |
| `tabs[].key` | `string` (enum) | Có | Khóa kỹ thuật của tab: `info`, `life_dd_tpd`, `ip` hoặc `health`. |
| `tabs[].label` | `string` | Có | Tên hiển thị của tab; không được rỗng. |
| `tabs[].source_url` | `string` (URL) | Có | URL nguồn của tab. |
| `tabs[].available` | `boolean` | Không | Cho biết tab có truy cập/lấy dữ liệu được hay không; mặc định `true`. |
| `tabs[].plain_text` | `string` | Không | Nội dung sạch dạng văn bản thuần; mặc định `""`. |
| `tabs[].markdown` | `string` | Không | Nội dung sạch dạng Markdown; mặc định `""`. |
| `tabs[].tables` | `array<object>` | Không | Các bảng tổng quát lấy từ tab. Mặc định `[]`. |
| `tabs[].classification_table` | `object hoặc null` | Không | Bảng phân loại/rating đã chuẩn hóa; `null` nếu tab không có bảng phù hợp. |
| `tabs[].content_hash` | `string (SHA-256) hoặc null` | Không | Hash của Markdown sạch trong tab, dùng để phát hiện thay đổi. |
| `tabs[].warnings` | `array<string>` | Không | Cảnh báo phát sinh khi làm sạch hoặc parse tab. Mặc định `[]`. |
| `tabs[].related_details` | `array<object>` | Không | Nội dung chi tiết lấy từ các link liên quan trong tab. Mặc định `[]`. |

### Ý nghĩa `tabs[].key`

| Giá trị | Nội dung |
| --- | --- |
| `info` | Thông tin y khoa tổng quát của bệnh. |
| `life_dd_tpd` | Bảng phân loại bảo hiểm Life, Dread Disease/Critical Illness và disability-related benefits. |
| `ip` | Bảng phân loại income protection/thời gian mất khả năng lao động. |
| `health` | Bảng quyền lợi/bảo hiểm sức khỏe như nằm viện, phẫu thuật, ngoại trú và thuốc mạn tính. |

### `tabs[].tables[]` — bảng tổng quát

| JSON path | Kiểu | Bắt buộc | Ý nghĩa |
| --- | --- | --- | --- |
| `tabs[].tables[].rows` | `array<array<string>>` | Không | Các dòng/cell của bảng theo đúng thứ tự nguồn. Mặc định `[]`; schema không áp đặt số cột cố định. |

## 7. `tabs[].classification_table` — bảng phân loại chuẩn hóa

| JSON path | Kiểu | Bắt buộc | Ý nghĩa |
| --- | --- | --- | --- |
| `tabs[].classification_table.headers` | `array<string>` | Không | Danh sách tiêu đề cột theo thứ tự nguồn. Mặc định `[]`. |
| `tabs[].classification_table.rows` | `array<object>` | Không | Danh sách phẳng toàn bộ dòng phân loại. Mặc định `[]`. |
| `tabs[].classification_table.tree` | `array<object>` | Không | Cùng dữ liệu phân loại nhưng được tổ chức thành cây cha-con. Mặc định `[]`. |
| `tabs[].classification_table.warnings` | `array<string>` | Không | Cảnh báo khi đọc header, level hoặc số cột. Mặc định `[]`. |

### `classification_table.rows[]` — một dòng dạng phẳng

| JSON path | Kiểu | Bắt buộc | Ý nghĩa / ràng buộc |
| --- | --- | --- | --- |
| `...rows[].classification_id` | `string` (SHA-256) | Có | ID ổn định được tạo từ toàn bộ `classification_path` sau khi chuẩn hóa chữ thường và khoảng trắng. |
| `...rows[].parent_classification_id` | `string (SHA-256) hoặc null` | Có | ID của node cha; chỉ node gốc (`level = 0`) được phép là `null`. |
| `...rows[].parent_classification` | `string hoặc null` | Có | Tên node cha; phải bằng phần tử áp chót của path, hoặc `null` ở node gốc. |
| `...rows[].classification` | `string` | Có | Tên điều kiện/nhóm phân loại hiện tại; phải bằng phần tử cuối của path. |
| `...rows[].level` | `integer` | Có | Độ sâu trong cây, bắt đầu từ `0`; phải bằng `classification_path.length - 1`. |
| `...rows[].classification_path` | `array<string>` | Có | Đường dẫn đầy đủ từ node gốc đến node hiện tại; có ít nhất một phần tử. |
| `...rows[].is_group` | `boolean` | Có | `true` nếu dòng chỉ là nhóm, tức không có rating và không có code. |
| `...rows[].ratings` | `object<string,string>` | Có | Map động từ tên cột quyền lợi sang giá trị rating gốc; schema không giới hạn tên key hoặc mã rating. |
| `...rows[].code` | `string hoặc null` | Có | Mã bệnh/phân loại ở cột `Code`; `null` nếu ô trống. |
| `...rows[].raw_cells` | `array<string>` | Không | Toàn bộ cell đã căn theo `headers`, giữ thứ tự cột để audit. Mặc định `[]`. |

Ví dụ `ratings` có thể chứa các key `Life`, `DD/CI`, `TPD own`, `TPD any`,
`ADism`, `ADB`, `LTC`, `D2/52`, `D4/52`, `D13/52`, `Hospitalisation`,
`Surgery`, `OPD` và `Chronic Medication`. Giá trị cần được giữ nguyên như nguồn,
ví dụ `D`, `CMO`, `EX`, `+25`, chuỗi hướng dẫn tham chiếu, hoặc chuỗi rỗng.

### `classification_table.tree[]` — một node dạng cây

Node cây có các field giống dòng phẳng, ngoại trừ không có `raw_cells` và có thêm
`children`. Cấu trúc này đệ quy: mỗi phần tử trong `children` lại là một node cùng kiểu.

| JSON path | Kiểu | Bắt buộc | Ý nghĩa |
| --- | --- | --- | --- |
| `...tree[].classification_id` | `string` (SHA-256) | Có | ID ổn định của node phân loại. |
| `...tree[].parent_classification_id` | `string (SHA-256) hoặc null` | Có | ID node cha; `null` ở node gốc. |
| `...tree[].parent_classification` | `string hoặc null` | Có | Tên node cha; `null` ở node gốc. |
| `...tree[].classification` | `string` | Có | Tên node hiện tại. |
| `...tree[].level` | `integer` | Có | Độ sâu của node, bắt đầu từ `0`. |
| `...tree[].classification_path` | `array<string>` | Có | Đường dẫn từ gốc đến node hiện tại. |
| `...tree[].is_group` | `boolean` | Có | Cho biết node chỉ đóng vai trò nhóm. |
| `...tree[].ratings` | `object<string,string>` | Có | Rating theo từng cột quyền lợi. |
| `...tree[].code` | `string hoặc null` | Có | Mã bệnh/phân loại nếu có. |
| `...tree[].children` | `array<object>` | Không | Danh sách node con. Mặc định `[]`. |

## 8. `tabs[].related_details[]` — nội dung liên quan

| JSON path | Kiểu | Bắt buộc | Ý nghĩa |
| --- | --- | --- | --- |
| `tabs[].related_details[].label` | `string` | Có | Nhãn/tên của link chi tiết; không được rỗng. |
| `tabs[].related_details[].url` | `string` (URL) | Có | URL của trang chi tiết liên quan. |
| `tabs[].related_details[].available` | `boolean` | Không | Trang chi tiết có lấy được nội dung hay không; mặc định `true`. |
| `tabs[].related_details[].plain_text` | `string` | Không | Nội dung sạch dạng văn bản thuần. Mặc định `""`. |
| `tabs[].related_details[].markdown` | `string` | Không | Nội dung sạch dạng Markdown. Mặc định `""`. |
| `tabs[].related_details[].content_hash` | `string (SHA-256) hoặc null` | Không | Hash của Markdown sạch; `null` nếu không có nội dung để hash. |
| `tabs[].related_details[].warnings` | `array<string>` | Không | Cảnh báo khi lấy/làm sạch trang chi tiết. Mặc định `[]`. |

## 9. `parse_metadata` — metadata parse

| JSON path | Kiểu | Bắt buộc | Ý nghĩa / ràng buộc |
| --- | --- | --- | --- |
| `parse_metadata.method` | `string` (enum) | Có | Phương pháp parse: `rules`, `llm` hoặc `rules+llm`. |
| `parse_metadata.model` | `string hoặc null` | Không | Tên model AI đã dùng; có thể `null` khi chỉ dùng rules. |
| `parse_metadata.prompt_version` | `string hoặc null` | Không | Phiên bản prompt; có thể `null` khi không dùng prompt. |
| `parse_metadata.parser_version` | `string` | Có | Phiên bản parser; không được rỗng. |
| `parse_metadata.confidence` | `number hoặc null` | Không | Độ tin cậy trong khoảng từ `0` đến `1`; `null` nếu không được tính. |
| `parse_metadata.warnings` | `array<string>` | Không | Các cảnh báo parse/coverage/provenance; mặc định `[]`. |

Một số warning thường gặp:

- `missing_field:<field>`: nguồn không có dữ liệu cho field y khoa tương ứng.
- `deterministic_full_content:<field>`: field được lấy đầy đủ bằng logic xác định.
- `incremental_unchanged_reused`: nội dung không đổi và kết quả trước được tái sử dụng.
- Các warning bắt đầu bằng `classification_`: vấn đề header, level, path hoặc số cột của bảng phân loại.

## 10. Nguyên tắc sử dụng dữ liệu

- `disease` là phần phù hợp nhất cho tìm kiếm, hiển thị tóm tắt và nghiệp vụ y khoa.
- `tabs[].classification_table.rows` phù hợp cho lọc, thống kê và xuất bảng; `tree` phù hợp cho UI phân cấp.
- `sections[].markdown`, `tabs[].markdown` và `raw_cells` giữ nội dung chi tiết để hiển thị/audit, không nên dùng thay cho field chuẩn hóa nếu field tương ứng đã tồn tại.
- `content_hash`, `document_id` và `classification_id` là ID/hash kỹ thuật, không phải dữ liệu y khoa.
- Không diễn giải mã rating trong `ratings` nếu chưa có bảng quy ước nghiệp vụ riêng; output hiện tại chủ ý giữ nguyên giá trị nguồn.
