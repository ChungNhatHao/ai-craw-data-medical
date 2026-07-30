# MVP Day 1 — Implementation Report

Status: **DONE**

Date: 2026-07-28

## Deliverables

- Python project yêu cầu Python `>=3.12,<3.13`.
- Dependency manifest và lockfile.
- FastAPI application lifecycle.
- Liveness và readiness endpoints.
- Pydantic Settings và `.env.example`.
- Loguru configuration có JSON mode.
- SQLite database, migration runner và job repository.
- LangGraph demo workflow dùng fake plugin.
- Playwright browser lifecycle manager.
- API và Chromium smoke commands.
- Unit/integration test skeleton.

## Source map

| Phần | Vị trí |
|---|---|
| App entrypoint | `main.py` |
| FastAPI factory/lifespan | `app/api/application.py` |
| Health endpoints | `app/api/routes_health.py` |
| Configuration | `app/core/config.py` |
| Logging | `app/utils/logging.py` |
| SQLite/migrations | `app/repositories/`, `migrations/` |
| LangGraph | `app/agents/` |
| Fake plugin | `app/plugins/fake.py` |
| Browser manager | `app/browser/manager.py` |
| Tests | `tests/unit/`, `tests/integration/` |

## Verification

Environment:

```text
Python 3.12.13
```

Results:

```text
ruff:   passed
mypy:   passed (24 source files)
pytest: 5 passed
API:    /live and /ready returned HTTP 200
Browser: Playwright Chromium smoke check passed
```

Commands:

```bash
.venv/bin/ruff check .
.venv/bin/mypy app
.venv/bin/pytest
bash scripts/smoke_api.sh
python -m app.browser.smoke
```

## Notes

- Browser binary dùng để kiểm thử trong phiên triển khai được đặt ở `/tmp`; môi
  trường mới cần chạy `playwright install chromium`.
- Docker packaging vẫn thuộc V2 Day 7 theo roadmap, không kéo sớm vào Day 1.
- Fake plugin chỉ chứng minh boundary/orchestration; login website thật bắt đầu
  ở Day 2.
- Credential thật chưa được thêm vào workspace.
