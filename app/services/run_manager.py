import asyncio
from datetime import UTC, datetime
from urllib.parse import urlparse

from app.core.config import Settings
from app.core.errors import CrawlerError, ErrorCode
from app.models.run import (
    RunRequest,
    RunSnapshot,
    RunStage,
    RunStageName,
    RunStartResponse,
    RunState,
    StageState,
)
from app.plugins.genre_manuals.plugin import GenreManualsPlugin
from app.repositories.database import Database
from app.repositories.jobs import JobRepository
from app.services.live_pipeline import LivePipelineRunner
from app.storage.artifacts import ArtifactStore

STAGE_LABELS = (
    (RunStageName.VALIDATE, "Kiểm tra yêu cầu"),
    (RunStageName.AUTHENTICATE, "Đăng nhập & session"),
    (RunStageName.NAVIGATE, "Tìm trang bệnh"),
    (RunStageName.DISCOVER, "Tìm & xác minh bệnh"),
    (RunStageName.PROFILE, "Quét cấu trúc nguồn"),
    (RunStageName.FETCH, "Tải dữ liệu gốc"),
    (RunStageName.CLEAN, "Làm sạch & Markdown"),
    (RunStageName.PARSE, "Structured JSON"),
    (RunStageName.COVERAGE, "Kiểm tra độ đầy đủ"),
    (RunStageName.REPORT, "Report & output"),
)


class RunManager:
    def __init__(self, settings: Settings, database: Database) -> None:
        self.settings = settings
        self.database = database
        self._runs: dict[str, RunSnapshot] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._lock = asyncio.Lock()

    async def start(self, request: RunRequest) -> RunStartResponse:
        self._validate_request(request)
        async with self._lock:
            if any(
                snapshot.state in {RunState.QUEUED, RunState.RUNNING}
                for snapshot in self._runs.values()
            ):
                raise RuntimeError("Một crawler run khác đang hoạt động")
            job = await JobRepository(self.database).create("genre_manuals")
            job_id = str(job.id)
            snapshot = RunSnapshot(
                job_id=job_id,
                stages=tuple(
                    RunStage(name=name, label=label)
                    for name, label in STAGE_LABELS
                ),
            )
            self._runs[job_id] = snapshot
            task = asyncio.create_task(
                self._execute(job_id, request),
                name=f"crawler-run-{job_id}",
            )
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            return RunStartResponse(job_id=job_id, state=snapshot.state)

    async def get(self, job_id: str) -> RunSnapshot | None:
        async with self._lock:
            snapshot = self._runs.get(job_id)
            return snapshot.model_copy(deep=True) if snapshot else None

    async def close(self) -> None:
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _execute(self, job_id: str, request: RunRequest) -> None:
        await self._set_run_state(job_id, RunState.RUNNING)
        try:
            await LivePipelineRunner(
                self.settings,
                self.database,
            ).run(
                job_id=job_id,
                request=request,
                emit=lambda name, state, message, current, total: self.emit(
                    job_id,
                    name,
                    state,
                    message,
                    current,
                    total,
                ),
            )
        except asyncio.CancelledError:
            await self._fail(
                job_id,
                ErrorCode.UNEXPECTED.value,
                "Run đã dừng khi ứng dụng shutdown",
            )
            raise
        except CrawlerError as exc:
            await JobRepository(self.database).update_status(
                job_id,
                "failed",
            )
            await self._fail(job_id, exc.code.value, str(exc))
            await self._persist_failure_report(job_id)
        except Exception:
            await JobRepository(self.database).update_status(
                job_id,
                "failed",
            )
            await self._fail(
                job_id,
                ErrorCode.UNEXPECTED.value,
                "Lỗi không mong đợi trong crawler pipeline",
            )
            await self._persist_failure_report(job_id)
        else:
            report = ArtifactStore(self.settings.output_root).load_job_report(
                job_id
            )
            state = (
                RunState.COMPLETED_WITH_ERRORS
                if report is not None and report.failed_items
                else RunState.COMPLETED
            )
            async with self._lock:
                snapshot = self._runs[job_id]
                self._runs[job_id] = snapshot.model_copy(
                    update={
                        "state": state,
                        "finished_at": datetime.now(UTC),
                        "report_available": report is not None,
                    }
                )

    async def emit(
        self,
        job_id: str,
        name: RunStageName,
        state: StageState,
        message: str,
        current: int,
        total: int,
    ) -> None:
        async with self._lock:
            snapshot = self._runs[job_id]
            now = datetime.now(UTC)
            stages = []
            for stage in snapshot.stages:
                if stage.name is not name:
                    stages.append(stage)
                    continue
                stages.append(
                    stage.model_copy(
                        update={
                            "state": state,
                            "message": message,
                            "current": current,
                            "total": total,
                            "started_at": (
                                stage.started_at
                                or (now if state is StageState.RUNNING else None)
                            ),
                            "finished_at": (
                                now
                                if state
                                in {StageState.COMPLETED, StageState.FAILED}
                                else None
                            ),
                        }
                    )
                )
            self._runs[job_id] = snapshot.model_copy(
                update={"stages": tuple(stages)}
            )

    async def _set_run_state(self, job_id: str, state: RunState) -> None:
        async with self._lock:
            snapshot = self._runs[job_id]
            self._runs[job_id] = snapshot.model_copy(update={"state": state})

    async def _fail(
        self,
        job_id: str,
        code: str,
        message: str,
    ) -> None:
        async with self._lock:
            snapshot = self._runs[job_id]
            stages = list(snapshot.stages)
            for index, stage in enumerate(stages):
                if stage.state is StageState.RUNNING:
                    stages[index] = stage.model_copy(
                        update={
                            "state": StageState.FAILED,
                            "message": message,
                            "finished_at": datetime.now(UTC),
                        }
                    )
                    break
            self._runs[job_id] = snapshot.model_copy(
                update={
                    "state": RunState.FAILED,
                    "stages": tuple(stages),
                    "error_code": code,
                    "error_message": message,
                    "finished_at": datetime.now(UTC),
                }
            )

    async def _persist_failure_report(self, job_id: str) -> None:
        from app.repositories.items import ItemRepository
        from app.services.reporting import ReportingService

        try:
            await ReportingService(
                jobs=JobRepository(self.database),
                items=ItemRepository(self.database),
                artifacts=ArtifactStore(self.settings.output_root),
            ).generate(job_id)
        except Exception:
            return
        async with self._lock:
            snapshot = self._runs[job_id]
            self._runs[job_id] = snapshot.model_copy(
                update={"report_available": True}
            )

    def _validate_request(self, request: RunRequest) -> None:
        parsed = urlparse(str(request.url))
        if parsed.scheme != "https" or parsed.hostname not in (
            GenreManualsPlugin.allowed_domains
        ):
            raise ValueError("URL phải là HTTPS thuộc domain genre-manuals.com")
        if not request.authorization_confirmed:
            raise ValueError(
                "Bạn phải xác nhận có quyền automation và lưu nội dung"
            )
        if (
            request.category_max_depth
            > self.settings.category_hard_max_depth
            or request.category_max_nodes
            > self.settings.category_hard_max_nodes
            or request.category_max_diseases
            > self.settings.category_hard_max_diseases
        ):
            raise ValueError(
                "Giới hạn mở rộng menu vượt hard limit của backend"
            )
        if request.agentic_discovery:
            if not self.settings.agentic_discovery_enabled:
                raise ValueError(
                    "Agentic Discovery chưa được bật ở cấu hình backend"
                )
            if self.settings.gemini_api_key is None:
                raise ValueError(
                    "GEMINI_API_KEY chưa được cấu hình ở backend"
                )
        if request.agentic_parsing:
            if not self.settings.agentic_parsing_enabled:
                raise ValueError(
                    "Agentic Parsing chưa được bật ở cấu hình backend"
                )
            if self.settings.gemini_api_key is None:
                raise ValueError(
                    "GEMINI_API_KEY chưa được cấu hình ở backend"
                )
        if request.ai_normalization and not self.settings.ai_normalization_enabled:
            raise ValueError(
                "AI Normalization chưa được bật ở cấu hình backend"
            )
        if request.ai_normalization and not request.agentic_parsing:
            raise ValueError(
                "AI Normalization yêu cầu bật Gemini Agentic Parsing"
            )
        if request.ai_normalization and self.settings.gemini_api_key is None:
            raise ValueError(
                "GEMINI_API_KEY chưa được cấu hình ở backend"
            )
