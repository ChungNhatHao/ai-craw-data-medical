# Incremental crawl and cross-job deduplication

## Goal

Mỗi bệnh vẫn được mở và thu thập lại một lần để kiểm tra cập nhật. Sau bước
làm sạch, hệ thống so sánh với lần crawl thành công gần nhất của cùng plugin và
`item_id`.

## Snapshot contract

Snapshot không chỉ dùng Markdown chính. Hash tổng hợp gồm:

- `main`: hash Markdown chính;
- `tab:info`;
- `tab:life_dd_tpd`;
- `tab:ip`;
- `tab:health`.

Mỗi thành phần tab bao gồm trạng thái available, hash Markdown, bảng dữ liệu và
hash của các trang read-only liên quan. Thứ tự tab và thứ tự related link không
làm thay đổi kết quả.

## Decision

- `new`: chưa có baseline thành công;
- `updated`: snapshot hiện tại khác baseline;
- `unchanged`: snapshot giống baseline.

Với `unchanged`, HTML, screenshot, tab raw và tab clean của lần kiểm tra mới vẫn
được giữ làm bằng chứng. `disease.json` cũ chỉ được tái sử dụng khi checksum và
toàn bộ `cleaner_version`, `parser_version`, `prompt_version`, `schema_hash`,
`model_version` đều tương thích. Nếu không tương thích, parser chạy lại.

## Audit and UI

Database và report lưu:

- snapshot hiện tại và snapshot trước;
- baseline job;
- thời điểm kiểm tra;
- trạng thái `new / updated / unchanged`;
- danh sách thành phần thay đổi.

UI hiển thị tổng số mới, cập nhật, không đổi và badge trên từng bệnh.

## Verification

- snapshot ổn định khi đổi thứ tự tab;
- thay đổi một tab được nhận diện đúng thành phần;
- hai job giống nhau: job thứ hai vẫn clean dữ liệu mới nhưng không gọi parser;
- lint, type-check và toàn bộ test hồi quy phải qua trước live canary.
