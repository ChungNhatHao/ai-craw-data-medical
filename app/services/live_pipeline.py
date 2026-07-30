import hashlib
from collections.abc import Awaitable, Callable

from playwright.async_api import Page

from app.agents.autocomplete_selection_agent import AutocompleteSelectionAgent
from app.agents.disease_detector import DiseaseDetector
from app.agents.disease_extraction_agent import DiseaseExtractionAgent
from app.agents.navigation_agent import NavigationAgent
from app.agents.normalization_agent import NormalizationAgent
from app.ai.agent_adapter import AgentModelPolicy, GeminiAgentAdapter
from app.ai.client import GeminiClient, GoogleGenAITransport
from app.browser.manager import BrowserManager
from app.browser.session import SessionStore
from app.core.config import Credentials, Settings
from app.core.errors import CrawlerError, ErrorCode
from app.models.artifacts import RawFetchPolicy
from app.models.batch import BatchPolicy
from app.models.crawl import JobStatus
from app.models.discovery import DiscoveredItem, DiscoveryPolicy
from app.models.disease import ParsingPolicy
from app.models.navigation import NavigationPolicy
from app.models.run import RunRequest, RunStageName, StageState
from app.parser.extractor import ContentExtractor
from app.parser.structured import RuleBasedStructuredClient
from app.plugins.genre_manuals.plugin import GenreManualsPlugin
from app.repositories.agent_audit import AgentAuditRepository
from app.repositories.attempts import AttemptRepository
from app.repositories.category_provenance import CategoryProvenanceRepository
from app.repositories.database import Database
from app.repositories.items import ItemRepository
from app.repositories.jobs import JobRepository
from app.services.agentic_discovery import AgenticDiscoveryService
from app.services.agentic_parsing import AgenticParsingService
from app.services.batch import BatchFetchService
from app.services.category_expansion import CategoryExpansionPolicy
from app.services.cleaning import CleaningService
from app.services.detail_fetch import DetailFetchService
from app.services.import_discovery import ImportedDiseaseDiscoveryService
from app.services.intelligent_discovery import IntelligentDiscoveryService
from app.services.navigation import NavigationDetectionLoop
from app.services.page_observer import PageObserver
from app.services.parsing import StructuredParsingService
from app.services.reporting import ReportingService
from app.services.session import SessionService
from app.storage.artifacts import ArtifactStore

ProgressEmitter = Callable[
    [RunStageName, StageState, str, int, int],
    Awaitable[None],
]


class LivePipelineRunner:
    def __init__(self, settings: Settings, database: Database) -> None:
        self.settings = settings
        self.database = database

    async def run(
        self,
        *,
        job_id: str,
        request: RunRequest,
        emit: ProgressEmitter,
    ) -> None:
        plugin = GenreManualsPlugin(
            base_url=str(request.url),
            navigation_timeout_ms=self.settings.browser_navigation_timeout_ms,
            selector_timeout_ms=self.settings.browser_selector_timeout_ms,
            detail_confidence_threshold=(
                self.settings.disease_detail_confidence_threshold
            ),
        )
        jobs = JobRepository(self.database)
        items = ItemRepository(self.database)
        attempts = AttemptRepository(self.database)
        artifacts = ArtifactStore(self.settings.output_root)

        await emit(
            RunStageName.VALIDATE,
            StageState.RUNNING,
            "Đang kiểm tra URL, giới hạn và quyền thực thi",
            0,
            1,
        )
        if not request.authorization_confirmed:
            raise CrawlerError(
                ErrorCode.AUTH_INVALID_CREDENTIALS,
                "Authorization confirmation is required",
            )
        plugin.canonicalize_url(str(request.url))
        await jobs.update_status(job_id, JobStatus.RUNNING.value)
        await emit(
            RunStageName.VALIDATE,
            StageState.COMPLETED,
            "URL và giới hạn hợp lệ",
            1,
            1,
        )

        username = request.username.get_secret_value()
        session_key = hashlib.sha256(username.encode("utf-8")).hexdigest()[:12]
        session_store = SessionStore(
            self.settings.session_root / f"genre_manuals-{session_key}.json"
        )
        credentials = Credentials(
            username=request.username,
            password=request.password,
        )
        agent_adapter = (
            self._build_agent_adapter(job_id)
            if (
                request.agentic_discovery
                or (
                    request.discovery_mode == "import"
                    and self.settings.gemini_api_key is not None
                )
            )
            else None
        )

        await emit(
            RunStageName.AUTHENTICATE,
            StageState.RUNNING,
            "Đang khởi động browser và kiểm tra session",
            0,
            1,
        )
        async with BrowserManager(
            headless=self.settings.browser_headless
        ) as manager:
            login = await SessionService(
                plugin,
                session_store,
            ).ensure_authenticated(
                manager.browser,
                credentials,
            )
            await emit(
                RunStageName.AUTHENTICATE,
                StageState.COMPLETED,
                (
                    "Đã tái sử dụng session an toàn"
                    if login.reused_session
                    else "Đăng nhập thành công và đã lưu session an toàn"
                ),
                1,
                1,
            )
            session = session_store.load()
            if session is None:
                raise CrawlerError(
                    ErrorCode.SESSION_STATE_INVALID,
                    "Authenticated session was not persisted",
                )
            context = await manager.browser.new_context(storage_state=session)
            try:
                page = await context.new_page()
                if request.discovery_mode == "import":
                    await self._prepare_import_navigation(
                        page=page,
                        plugin=plugin,
                        emit=emit,
                    )
                    discovered = await self._discover_imported(
                        page=page,
                        plugin=plugin,
                        items=items,
                        artifacts=artifacts,
                        job_id=job_id,
                        disease_names=request.disease_names,
                        expand_categories=request.expand_disease_categories,
                        category_max_depth=request.category_max_depth,
                        category_max_nodes=request.category_max_nodes,
                        category_max_diseases=request.category_max_diseases,
                        adapter=agent_adapter,
                        emit=emit,
                    )
                elif request.agentic_discovery:
                    await self._prepare_agentic_navigation(
                        page=page,
                        plugin=plugin,
                        emit=emit,
                    )
                    discovered = await self._discover_agentic(
                        page=page,
                        plugin=plugin,
                        items=items,
                        job_id=job_id,
                        max_items=request.max_items,
                        adapter=agent_adapter,
                        emit=emit,
                    )
                else:
                    await self._navigate(
                        page=page,
                        plugin=plugin,
                        emit=emit,
                    )
                    discovered = await self._discover(
                        page=page,
                        plugin=plugin,
                        items=items,
                        job_id=job_id,
                        max_items=request.max_items,
                        emit=emit,
                    )
                await self._fetch(
                    page=page,
                    plugin=plugin,
                    jobs=jobs,
                    items=items,
                    attempts=attempts,
                    artifacts=artifacts,
                    job_id=job_id,
                    item_count=len(discovered),
                    emit=emit,
                )
            finally:
                await context.close()

        await self._clean(
            plugin=plugin,
            items=items,
            attempts=attempts,
            artifacts=artifacts,
            job_id=job_id,
            emit=emit,
        )
        await self._parse(
            plugin=plugin,
            items=items,
            attempts=attempts,
            artifacts=artifacts,
            job_id=job_id,
            adapter=agent_adapter,
            use_agentic=request.agentic_discovery,
            use_ai_normalization=request.ai_normalization,
            emit=emit,
        )
        counts = await items.count_by_status(job_id)
        terminal = (
            JobStatus.COMPLETED_WITH_ERRORS
            if counts.get("retryable_failed", 0)
            else JobStatus.COMPLETED
        )
        await jobs.update_status(job_id, terminal.value)
        await emit(
            RunStageName.REPORT,
            StageState.RUNNING,
            "Đang tổng hợp report và kiểm tra artifact",
            0,
            1,
        )
        report = await ReportingService(
            jobs=jobs,
            items=items,
            artifacts=artifacts,
        ).generate(job_id)
        await emit(
            RunStageName.REPORT,
            StageState.COMPLETED,
            (
                f"Hoàn tất: {report.successful_items} thành công, "
                f"{report.failed_items} lỗi"
            ),
            1,
            1,
        )

    async def _navigate(
        self,
        *,
        page: Page,
        plugin: GenreManualsPlugin,
        emit: ProgressEmitter,
    ) -> None:
        await emit(
            RunStageName.NAVIGATE,
            StageState.RUNNING,
            "Đang mở website và xác nhận session trước khi tìm trang bệnh",
            0,
            self.settings.navigation_max_hops_per_item,
        )
        if not await plugin.validate_session(page):
            raise CrawlerError(
                ErrorCode.AUTH_SESSION_EXPIRED,
                "Session không còn hợp lệ trong crawler context",
            )
        result = await NavigationDetectionLoop(
            plugin,
            NavigationPolicy(
                max_hops=self.settings.navigation_max_hops_per_item,
                max_same_fingerprint=(
                    self.settings.navigation_max_same_fingerprint
                ),
                max_no_progress=self.settings.navigation_max_no_progress,
            ),
        ).locate_disease_detail(page)
        await emit(
            RunStageName.NAVIGATE,
            StageState.COMPLETED,
            f"Đã xác nhận disease detail sau {result.hop_count} bước",
            result.hop_count,
            result.hop_count,
        )

    async def _prepare_agentic_navigation(
        self,
        *,
        page: Page,
        plugin: GenreManualsPlugin,
        emit: ProgressEmitter,
    ) -> None:
        await emit(
            RunStageName.NAVIGATE,
            StageState.RUNNING,
            "Đang mở website để Gemini Navigation Agent quan sát",
            0,
            1,
        )
        if not await plugin.validate_session(page):
            raise CrawlerError(
                ErrorCode.AUTH_SESSION_EXPIRED,
                "Session không còn hợp lệ trong agentic crawler context",
            )
        await emit(
            RunStageName.NAVIGATE,
            StageState.COMPLETED,
            "Session hợp lệ; quyền điều hướng được giới hạn bằng candidate allowlist",
            1,
            1,
        )

    async def _prepare_import_navigation(
        self,
        *,
        page: Page,
        plugin: GenreManualsPlugin,
        emit: ProgressEmitter,
    ) -> None:
        await emit(
            RunStageName.NAVIGATE,
            StageState.RUNNING,
            "Đang mở website và định vị ô Start searching…",
            0,
            1,
        )
        if not await plugin.validate_session(page):
            raise CrawlerError(
                ErrorCode.AUTH_SESSION_EXPIRED,
                "Session không còn hợp lệ trong crawler import",
            )
        if not await page.locator("#searchTerm").count():
            raise CrawlerError(
                ErrorCode.PAGE_TYPE_UNKNOWN,
                "Không tìm thấy ô Start searching… trên website",
            )
        await emit(
            RunStageName.NAVIGATE,
            StageState.COMPLETED,
            "Đã sẵn sàng tìm bệnh từ danh sách import",
            1,
            1,
        )

    async def _discover_imported(
        self,
        *,
        page: Page,
        plugin: GenreManualsPlugin,
        items: ItemRepository,
        artifacts: ArtifactStore,
        job_id: str,
        disease_names: tuple[str, ...],
        expand_categories: bool,
        category_max_depth: int,
        category_max_nodes: int,
        category_max_diseases: int,
        adapter: GeminiAgentAdapter | None,
        emit: ProgressEmitter,
    ) -> list[DiscoveredItem]:
        total = len(disease_names)
        await emit(
            RunStageName.DISCOVER,
            StageState.RUNNING,
            f"Đang tìm 0/{total} tên bệnh đã import",
            0,
            total,
        )

        async def progress(
            matched: int,
            processed: int,
            expected: int,
            disease_name: str,
            result: str,
        ) -> None:
            label = "đã xác nhận" if result == "matched" else "không tìm thấy"
            await emit(
                RunStageName.DISCOVER,
                StageState.RUNNING,
                (
                    f"{processed}/{expected}: {disease_name} — {label} · "
                    f"đã khớp {matched}"
                ),
                processed,
                expected,
            )

        service = ImportedDiseaseDiscoveryService(
            plugin=plugin,
            items=items,
            artifacts=artifacts,
            autocomplete_agent=(
                AutocompleteSelectionAgent(adapter)
                if adapter is not None
                else None
            ),
        )
        if expand_categories:

            async def category_progress(
                visited: int,
                queued: int,
                confirmed: int,
            ) -> None:
                await emit(
                    RunStageName.DISCOVER,
                    StageState.RUNNING,
                    (
                        f"Mở rộng menu: {visited} node đã kiểm tra · "
                        f"{queued} đang chờ · {confirmed} bệnh xác nhận"
                    ),
                    confirmed,
                    category_max_diseases,
                )

            discovered, unmatched = (
                await service.run_with_category_expansion(
                    page,
                    job_id=job_id,
                    disease_names=disease_names,
                    policy=CategoryExpansionPolicy(
                        max_depth=category_max_depth,
                        max_nodes=category_max_nodes,
                        max_diseases=category_max_diseases,
                    ),
                    provenance_repository=CategoryProvenanceRepository(
                        self.database
                    ),
                    progress=progress,
                    category_progress=category_progress,
                )
            )
        else:
            discovered, unmatched = await service.run(
                page,
                job_id=job_id,
                disease_names=disease_names,
                progress=progress,
            )
        suffix = (
            f"; không tìm thấy: {', '.join(unmatched)}"
            if unmatched
            else ""
        )
        await emit(
            RunStageName.DISCOVER,
            StageState.COMPLETED,
            (
                f"Import đã xác nhận {len(discovered)} bệnh từ {total} tên gốc"
                f"{suffix}"
            ),
            len(discovered),
            max(len(discovered), 1),
        )
        return discovered

    async def _discover_agentic(
        self,
        *,
        page: Page,
        plugin: GenreManualsPlugin,
        items: ItemRepository,
        job_id: str,
        max_items: int,
        adapter: GeminiAgentAdapter | None,
        emit: ProgressEmitter,
    ) -> list[DiscoveredItem]:
        if adapter is None:
            raise CrawlerError(
                ErrorCode.GEMINI_AUTH_FAILED,
                "Gemini adapter is required for agentic discovery",
            )
        await emit(
            RunStageName.DISCOVER,
            StageState.RUNNING,
            "Gemini đang observe → navigate → xác minh trang bệnh",
            0,
            max_items,
        )

        async def progress(
            accepted: int,
            pages: int,
            hops: int,
            reason: str,
        ) -> None:
            await emit(
                RunStageName.DISCOVER,
                StageState.RUNNING,
                (
                    f"Gemini xác nhận {accepted}/{max_items} bệnh · "
                    f"{pages} trang · {hops} hops · {reason}"
                ),
                accepted,
                max_items,
            )

        discovered = await AgenticDiscoveryService(
            plugin=plugin,
            items=items,
            audit=AgentAuditRepository(self.database),
            observer=PageObserver(
                plugin,
                max_text_chars=self.settings.gemini_max_input_chars,
            ),
            navigation_agent=NavigationAgent(adapter),
            disease_detector=DiseaseDetector(adapter),
            output_root=self.settings.output_root,
            policy=DiscoveryPolicy(
                max_items=max_items,
                max_pages=self.settings.crawl_max_pages,
                max_no_new_rounds=self.settings.discovery_max_no_new_rounds,
            ),
            max_hops=max(
                self.settings.navigation_max_hops_per_item,
                max_items * 6,
            ),
            disease_confidence_threshold=(
                self.settings.gemini_disease_confidence_threshold
            ),
        ).run(page, job_id=job_id, progress=progress)
        await emit(
            RunStageName.DISCOVER,
            StageState.COMPLETED,
            (
                f"Gemini Agentic Discovery đã xác nhận "
                f"{len(discovered)} bệnh"
            ),
            len(discovered),
            max_items,
        )
        return discovered

    async def _discover(
        self,
        *,
        page: Page,
        plugin: GenreManualsPlugin,
        items: ItemRepository,
        job_id: str,
        max_items: int,
        emit: ProgressEmitter,
    ) -> list[DiscoveredItem]:
        await emit(
            RunStageName.DISCOVER,
            StageState.RUNNING,
            "AI đang mở rộng cây Medical và kiểm tra từng trang ứng viên",
            0,
            max_items,
        )

        async def progress(
            accepted: int,
            evaluated: int,
            queued: int,
            page_type: str,
        ) -> None:
            await emit(
                RunStageName.DISCOVER,
                StageState.RUNNING,
                (
                    f"AI đã xác nhận {accepted}/{max_items} bệnh · "
                    f"kiểm tra {evaluated} trang · còn {queued} ứng viên · "
                    f"trang hiện tại: {page_type}"
                ),
                accepted,
                max_items,
            )

        result = await IntelligentDiscoveryService(
            plugin=plugin,
            items=items,
            output_root=self.settings.output_root,
            policy=DiscoveryPolicy(
                max_items=max_items,
                max_pages=self.settings.crawl_max_pages,
                max_no_new_rounds=self.settings.discovery_max_no_new_rounds,
            ),
        ).run(page, job_id=job_id, progress=progress)
        selected = list(result.items)
        await emit(
            RunStageName.DISCOVER,
            StageState.COMPLETED,
            (
                f"AI xác nhận {len(selected)} bệnh sau khi kiểm tra "
                f"{result.pages_evaluated} trang ({result.stopped_reason})"
            ),
            len(selected),
            max_items,
        )
        return selected

    async def _fetch(
        self,
        *,
        page: Page,
        plugin: GenreManualsPlugin,
        jobs: JobRepository,
        items: ItemRepository,
        attempts: AttemptRepository,
        artifacts: ArtifactStore,
        job_id: str,
        item_count: int,
        emit: ProgressEmitter,
    ) -> None:
        if item_count == 0:
            raise CrawlerError(
                ErrorCode.DISEASE_NOT_CONFIRMED,
                "Discovery completed without a confirmed disease page",
            )
        await emit(
            RunStageName.FETCH,
            StageState.RUNNING,
            f"Đang tải raw HTML và ảnh bằng chứng cho {item_count} item",
            0,
            item_count,
        )
        result = await BatchFetchService(
            jobs=jobs,
            items=items,
            artifacts=artifacts,
            detail_fetch=DetailFetchService(
                plugin=plugin,
                items=items,
                attempts=attempts,
                artifacts=artifacts,
                policy=RawFetchPolicy(
                    max_attempts=self.settings.fetch_max_attempts,
                    base_delay_seconds=self.settings.fetch_retry_base_seconds,
                    max_delay_seconds=self.settings.fetch_retry_max_seconds,
                    capture_screenshot=self.settings.capture_screenshot,
                ),
            ),
            policy=BatchPolicy(max_items=item_count),
        ).run(page, job_id=job_id)
        if result.status is JobStatus.PAUSED:
            raise CrawlerError(
                ErrorCode.AUTH_SESSION_EXPIRED,
                f"Batch đã pause: {result.stopped_reason}",
            )
        await emit(
            RunStageName.FETCH,
            StageState.COMPLETED,
            (
                f"Fetch xong: {result.fetched_count} thành công, "
                f"{result.failed_count} lỗi"
            ),
            result.processed_count,
            item_count,
        )

    async def _clean(
        self,
        *,
        plugin: GenreManualsPlugin,
        items: ItemRepository,
        attempts: AttemptRepository,
        artifacts: ArtifactStore,
        job_id: str,
        emit: ProgressEmitter,
    ) -> None:
        candidates = await items.list_by_status(job_id, ("fetched", "cleaned"))
        await emit(
            RunStageName.CLEAN,
            StageState.RUNNING,
            f"Đang làm sạch {len(candidates)} item và tạo Markdown",
            0,
            len(candidates),
        )
        service = CleaningService(
            plugin=plugin,
            items=items,
            attempts=attempts,
            artifacts=artifacts,
            extractor=ContentExtractor(minimum_chars=50),
        )
        completed = 0
        for item in candidates:
            try:
                await service.run(job_id=job_id, item=item)
            except CrawlerError:
                pass
            completed += 1
            await emit(
                RunStageName.CLEAN,
                StageState.RUNNING,
                f"Đã làm sạch {completed}/{len(candidates)} item",
                completed,
                len(candidates),
            )
        await emit(
            RunStageName.CLEAN,
            StageState.COMPLETED,
            f"Hoàn tất làm sạch {completed} item",
            completed,
            len(candidates),
        )

    async def _parse(
        self,
        *,
        plugin: GenreManualsPlugin,
        items: ItemRepository,
        attempts: AttemptRepository,
        artifacts: ArtifactStore,
        job_id: str,
        adapter: GeminiAgentAdapter | None,
        use_agentic: bool,
        use_ai_normalization: bool,
        emit: ProgressEmitter,
    ) -> None:
        candidates = await items.list_by_status(job_id, ("cleaned", "parsed"))
        await emit(
            RunStageName.PARSE,
            StageState.RUNNING,
            f"Đang tạo disease JSON cho {len(candidates)} item",
            0,
            len(candidates),
        )
        policy = ParsingPolicy(
            timeout_seconds=self.settings.parse_timeout_seconds,
            max_model_calls=self.settings.parse_max_model_calls,
            max_input_chars=self.settings.parse_max_input_chars,
        )
        if use_agentic:
            if adapter is None:
                raise CrawlerError(
                    ErrorCode.GEMINI_AUTH_FAILED,
                    "Gemini adapter is required for disease extraction",
                )
            service: StructuredParsingService | AgenticParsingService = (
                AgenticParsingService(
                    extraction_agent=DiseaseExtractionAgent(adapter),
                    normalization_agent=(
                        NormalizationAgent(adapter)
                        if use_ai_normalization
                        else None
                    ),
                    plugin=plugin,
                    items=items,
                    attempts=attempts,
                    artifacts=artifacts,
                    extractor=ContentExtractor(minimum_chars=50),
                    language="en",
                    model_version=self.settings.gemini_extraction_model,
                    policy=policy,
                )
            )
        else:
            service = StructuredParsingService(
                client=RuleBasedStructuredClient(),
                items=items,
                attempts=attempts,
                artifacts=artifacts,
                language="en",
                policy=policy,
            )
        completed = 0
        for item in candidates:
            try:
                await service.run(job_id=job_id, item=item)
            except CrawlerError:
                pass
            completed += 1
            await emit(
                RunStageName.PARSE,
                StageState.RUNNING,
                f"Đã parse {completed}/{len(candidates)} item",
                completed,
                len(candidates),
            )
        await emit(
            RunStageName.PARSE,
            StageState.COMPLETED,
            f"Hoàn tất structured parsing {completed} item",
            completed,
            len(candidates),
        )

    def _build_agent_adapter(self, job_id: str) -> GeminiAgentAdapter:
        api_key = self.settings.gemini_api_key
        if api_key is None:
            raise CrawlerError(
                ErrorCode.GEMINI_AUTH_FAILED,
                "GEMINI_API_KEY is required for agentic execution",
            )
        return GeminiAgentAdapter(
            client=GeminiClient(
                transport=GoogleGenAITransport(
                    api_key=api_key,
                    timeout_seconds=self.settings.gemini_timeout_seconds,
                ),
                timeout_seconds=self.settings.gemini_timeout_seconds,
                max_retries=self.settings.gemini_max_retries,
                retry_base_seconds=self.settings.gemini_retry_base_seconds,
                retry_max_seconds=self.settings.gemini_retry_max_seconds,
            ),
            models=AgentModelPolicy(
                navigation=self.settings.gemini_navigation_model,
                disease_detector=self.settings.gemini_detector_model,
                disease_extraction=self.settings.gemini_extraction_model,
                normalization=self.settings.gemini_normalization_model,
            ),
            audit=AgentAuditRepository(self.database),
            job_id=job_id,
            max_calls=self.settings.gemini_max_calls_per_job,
        )
