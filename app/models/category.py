from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from app.models.navigation import PageType


class CategoryReasonCode(StrEnum):
    EXACT_TITLE_NOT_FOUND = "exact_title_not_found"
    SINGULAR_PLURAL_CATEGORY_MATCH = "singular_plural_category_match"
    AMBIGUOUS_SINGULAR_PLURAL_RESULTS = "ambiguous_singular_plural_results"
    SEARCH_NAVIGATION_TIMEOUT = "search_navigation_timeout"
    SEARCH_INPUT_NOT_FOUND = "search_input_not_found"
    CATEGORY_CONFIRMED = "category_confirmed"
    CATEGORY_EMPTY = "category_empty"
    CATEGORY_CHILD_ENQUEUED = "category_child_enqueued"
    CATEGORY_DEPTH_LIMIT = "category_depth_limit"
    CATEGORY_NODE_LIMIT = "category_node_limit"
    CATEGORY_DISEASE_LIMIT = "category_disease_limit"
    DUPLICATE_CANONICAL_URL = "duplicate_canonical_url"
    DISEASE_DETAIL_CONFIRMED = "disease_detail_confirmed"
    CANDIDATE_NOT_DISEASE_DETAIL = "candidate_not_disease_detail"
    CANDIDATE_NOT_STABLE_DISEASE_DETAIL = (
        "candidate_not_stable_disease_detail"
    )
    PAGE_TYPE_UNKNOWN = "page_type_unknown"
    CONTENT_NOT_READY = "content_not_ready"


class CategoryNodeStatus(StrEnum):
    QUEUED = "queued"
    CONFIRMED = "confirmed"
    SKIPPED = "skipped"
    FAILED = "failed"
    LIMIT_REACHED = "limit_reached"


class SearchMatchStrategy(StrEnum):
    EXACT_NORMALIZED = "exact_normalized"
    SINGULAR_PLURAL_CATEGORY = "singular_plural_category"


CATEGORY_REASON_VI: dict[CategoryReasonCode, str] = {
    CategoryReasonCode.EXACT_TITLE_NOT_FOUND: "Không tìm thấy tiêu đề khớp chính xác.",
    CategoryReasonCode.SINGULAR_PLURAL_CATEGORY_MATCH: (
        "Đã chọn menu bệnh theo quy tắc số ít/số nhiều an toàn."
    ),
    CategoryReasonCode.AMBIGUOUS_SINGULAR_PLURAL_RESULTS: (
        "Có nhiều kết quả số ít/số nhiều nên không thể tự động chọn."
    ),
    CategoryReasonCode.SEARCH_NAVIGATION_TIMEOUT: "Trang tìm kiếm phản hồi quá thời gian.",
    CategoryReasonCode.SEARCH_INPUT_NOT_FOUND: "Không tìm thấy ô nhập tìm kiếm.",
    CategoryReasonCode.CATEGORY_CONFIRMED: "Đã xác nhận đây là menu nhóm bệnh.",
    CategoryReasonCode.CATEGORY_EMPTY: "Menu nhóm bệnh không có mục con hợp lệ.",
    CategoryReasonCode.CATEGORY_CHILD_ENQUEUED: "Đã đưa mục con vào hàng đợi kiểm tra.",
    CategoryReasonCode.CATEGORY_DEPTH_LIMIT: "Đã đạt giới hạn độ sâu menu.",
    CategoryReasonCode.CATEGORY_NODE_LIMIT: "Đã đạt giới hạn số nút menu.",
    CategoryReasonCode.CATEGORY_DISEASE_LIMIT: "Đã đạt giới hạn số bệnh con.",
    CategoryReasonCode.DUPLICATE_CANONICAL_URL: "URL chuẩn đã được kiểm tra trước đó.",
    CategoryReasonCode.DISEASE_DETAIL_CONFIRMED: "Đã xác nhận trang nội dung một bệnh.",
    CategoryReasonCode.CANDIDATE_NOT_DISEASE_DETAIL: (
        "Mục ứng viên không phải trang nội dung một bệnh."
    ),
    CategoryReasonCode.CANDIDATE_NOT_STABLE_DISEASE_DETAIL: (
        "Loại trang bệnh thay đổi khi kiểm tra ổn định lần hai."
    ),
    CategoryReasonCode.PAGE_TYPE_UNKNOWN: "Không xác định được loại trang.",
    CategoryReasonCode.CONTENT_NOT_READY: "Nội dung trang chưa sẵn sàng.",
}

CATEGORY_REASON_ACTIONS_VI: dict[CategoryReasonCode, tuple[str, ...]] = {
    CategoryReasonCode.EXACT_TITLE_NOT_FOUND: (
        "Thử đối chiếu số ít/số nhiều có giới hạn.",
        "Bỏ qua nếu không có đúng một ứng viên.",
    ),
    CategoryReasonCode.SINGULAR_PLURAL_CATEGORY_MATCH: (
        "Mở ứng viên cùng miền.",
        "Chỉ chấp nhận nếu trang được xác nhận là menu bệnh.",
    ),
    CategoryReasonCode.AMBIGUOUS_SINGULAR_PLURAL_RESULTS: (
        "Không tự động chọn kết quả.",
        "Ghi cảnh báo để người vận hành kiểm tra.",
    ),
    CategoryReasonCode.SEARCH_NAVIGATION_TIMEOUT: (
        "Ghi lỗi của tên bệnh hiện tại.",
        "Tiếp tục tên import kế tiếp.",
    ),
    CategoryReasonCode.SEARCH_INPUT_NOT_FOUND: (
        "Dừng tìm kiếm tên hiện tại.",
        "Ghi hướng dẫn kiểm tra selector tìm kiếm.",
    ),
    CategoryReasonCode.CATEGORY_CONFIRMED: (
        "Lấy các mục con trực tiếp.",
        "Đưa mục con hợp lệ vào hàng đợi theo thứ tự menu.",
    ),
    CategoryReasonCode.CATEGORY_EMPTY: (
        "Ghi menu rỗng vào audit.",
        "Tiếp tục nút kế tiếp.",
    ),
    CategoryReasonCode.CATEGORY_CHILD_ENQUEUED: (
        "Giữ đường dẫn menu cha-con.",
        "Kiểm tra nút khi đến lượt trong hàng đợi.",
    ),
    CategoryReasonCode.CATEGORY_DEPTH_LIMIT: (
        "Không mở rộng sâu hơn.",
        "Giữ kết quả hợp lệ đã thu thập.",
    ),
    CategoryReasonCode.CATEGORY_NODE_LIMIT: (
        "Dừng nhận thêm nút.",
        "Hoàn tất một phần với dữ liệu hiện có.",
    ),
    CategoryReasonCode.CATEGORY_DISEASE_LIMIT: (
        "Dừng nhận thêm bệnh con.",
        "Hoàn tất một phần với dữ liệu hiện có.",
    ),
    CategoryReasonCode.DUPLICATE_CANONICAL_URL: (
        "Không tải lại URL.",
        "Giữ thêm đường dẫn provenance nếu đây là bệnh đã xác nhận.",
    ),
    CategoryReasonCode.DISEASE_DETAIL_CONFIRMED: (
        "Lưu provenance cha-con.",
        "Đưa bệnh vào pipeline nội dung hiện có.",
    ),
    CategoryReasonCode.CANDIDATE_NOT_DISEASE_DETAIL: (
        "Không tạo crawl item.",
        "Tiếp tục nút kế tiếp.",
    ),
    CategoryReasonCode.CANDIDATE_NOT_STABLE_DISEASE_DETAIL: (
        "Không tạo crawl item.",
        "Ghi hai kết quả phân loại để kiểm tra.",
    ),
    CategoryReasonCode.PAGE_TYPE_UNKNOWN: (
        "Ghi tín hiệu phân loại.",
        "Tiếp tục nút kế tiếp.",
    ),
    CategoryReasonCode.CONTENT_NOT_READY: (
        "Ghi trạng thái nội dung.",
        "Bỏ qua nút mà không chặn các mục cùng cấp.",
    ),
}


class CategoryDiscoveryNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    root_query: str = Field(min_length=1, max_length=500)
    label: str = Field(min_length=1, max_length=1_000)
    url: HttpUrl
    canonical_url: HttpUrl
    parent_url: HttpUrl | None = None
    menu_path: tuple[str, ...] = Field(min_length=1, max_length=9)
    depth: int = Field(ge=0, le=8)
    page_type: PageType
    confidence: float = Field(ge=0, le=1)
    status: CategoryNodeStatus
    reason_code: CategoryReasonCode

    @model_validator(mode="after")
    def validate_path(self) -> "CategoryDiscoveryNode":
        if self.depth != len(self.menu_path) - 1:
            raise ValueError("depth must equal menu_path length minus one")
        if self.depth > 0 and self.parent_url is None:
            raise ValueError("A child category node requires parent_url")
        return self

    @property
    def reason_vi(self) -> str:
        return CATEGORY_REASON_VI[self.reason_code]

    @property
    def action_steps_vi(self) -> tuple[str, ...]:
        return CATEGORY_REASON_ACTIONS_VI[self.reason_code]


class CategoryItemProvenance(BaseModel):
    """One root/menu path leading to one deduplicated disease item."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    job_id: str = Field(min_length=1)
    item_id: str = Field(min_length=64, max_length=64)
    root_query: str = Field(min_length=1, max_length=500)
    parent_url: HttpUrl | None = None
    menu_path: tuple[str, ...] = Field(min_length=1, max_length=9)
    depth: int = Field(ge=0, le=8)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @model_validator(mode="after")
    def validate_path(self) -> "CategoryItemProvenance":
        if self.depth != len(self.menu_path) - 1:
            raise ValueError("depth must equal menu_path length minus one")
        if self.depth > 0 and self.parent_url is None:
            raise ValueError("Child disease provenance requires parent_url")
        return self
