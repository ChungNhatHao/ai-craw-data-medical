# Gemini Agentic Flow — Implementation Report

Date: 2026-07-29

## Outcome

Agentic flow đã được triển khai sau feature flags và kiểm thử offline. Baseline
crawler giữ nguyên khi flags tắt. Live Gemini chưa chạy vì backend hiện không có
`GEMINI_API_KEY` và decision G-01 chưa được xác nhận riêng.

## Implemented

- Official `google-genai` SDK transport.
- Structured Pydantic outputs, timeout, retry/backoff và provider error mapping.
- Per-job model-call budget.
- Gemini key là backend `SecretStr`; không xuất hiện trong UI.
- Navigation Agent với candidate allowlist.
- Disease Detector yêu cầu evidence và grounding.
- Disease Extraction Agent có evidence theo field.
- Optional Normalization Agent chỉ được sửa field ambiguous.
- BeautifulSoup-first boundary; content agents không nhận raw HTML/DOM.
- Recursive payload guard chặn HTML hoặc forbidden keys.
- LangGraph `observe → classify → detect → navigate` step.
- Rule classifier và Gemini phải cùng xác nhận disease detail.
- SQLite `agent_decisions` và `model_calls`.
- Agent trace API và UI feature controls.
- `disease-draft.json`, `normalization.json`, `agent-summary.json`.
- Feature flags và health state `ready|disabled|misconfigured`.

## Verification

- Ruff: clean.
- Strict Mypy: clean.
- Automated tests: 81 passed.
- Offline tests bao phủ Gemini retry/schema, content guard, four agent contracts,
  agent adapter audit/budget, LangGraph discovery và agentic parsing.
- Không có live Gemini call trong lần triển khai này.

## Runtime flags

```text
AGENTIC_DISCOVERY_ENABLED=false
AI_NORMALIZATION_ENABLED=false
GEMINI_API_KEY=
```

Khi credential gate hoàn tất:

1. Đặt key trong backend environment/secret manager.
2. Xác nhận content đã sanitize được phép gửi tới Gemini.
3. Bật `AGENTIC_DISCOVERY_ENABLED=true`.
4. Chạy canary 5 bệnh.
5. Đánh giá trace, grounding, token và latency.
6. Bật `AI_NORMALIZATION_ENABLED=true` sau khi canary discovery/extraction đạt.
7. Chạy canary 25 bệnh.

## Known limitation

Ambiguity detector hiện bảo thủ: deterministic normalization xử lý exact
duplicates và không gọi AI khi không phát hiện ambiguity rõ. Điều này giữ chi
phí và rủi ro thấp; tập eval live sẽ được dùng để mở rộng ambiguity rules.

