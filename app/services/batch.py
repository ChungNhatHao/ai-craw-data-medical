from playwright.async_api import Page

from app.core.errors import CrawlerError, ErrorCode
from app.models.batch import BatchPolicy, BatchResult
from app.models.crawl import JobStatus
from app.repositories.items import ItemRepository
from app.repositories.jobs import JobRepository
from app.services.detail_fetch import DetailFetchService
from app.storage.artifacts import ArtifactStore

STOP_BATCH_ERRORS = frozenset(
    {
        ErrorCode.AUTH_INVALID_CREDENTIALS,
        ErrorCode.AUTH_SESSION_EXPIRED,
        ErrorCode.AUTH_MFA_OR_CAPTCHA,
    }
)


class BatchFetchService:
    def __init__(
        self,
        *,
        jobs: JobRepository,
        items: ItemRepository,
        artifacts: ArtifactStore,
        detail_fetch: DetailFetchService,
        policy: BatchPolicy,
    ) -> None:
        self.jobs = jobs
        self.items = items
        self.artifacts = artifacts
        self.detail_fetch = detail_fetch
        self.policy = policy

    async def run(self, page: Page, *, job_id: str) -> BatchResult:
        await self.jobs.resume(job_id)
        recovered_count = await self._recover_interrupted_items(job_id)
        processed_count = 0
        fetched_count = 0
        failed_count = 0

        while processed_count < self.policy.max_items:
            if await self.jobs.is_stop_requested(job_id):
                await self.jobs.mark_paused(job_id)
                return await self._result(
                    job_id,
                    JobStatus.PAUSED,
                    processed_count,
                    fetched_count,
                    failed_count,
                    recovered_count,
                    "pause_requested",
                )

            item = await self.items.select_next_discovered(job_id)
            if item is None:
                return await self._finalize(
                    job_id,
                    processed_count,
                    fetched_count,
                    failed_count,
                    recovered_count,
                )

            processed_count += 1
            try:
                await self.detail_fetch.run(page, job_id=job_id, item=item)
            except CrawlerError as exc:
                failed_count += 1
                if exc.code in STOP_BATCH_ERRORS:
                    await self.jobs.request_pause(job_id)
                    await self.jobs.mark_paused(job_id)
                    return await self._result(
                        job_id,
                        JobStatus.PAUSED,
                        processed_count,
                        fetched_count,
                        failed_count,
                        recovered_count,
                        exc.code.value.lower(),
                    )
            else:
                fetched_count += 1

        remaining = await self._remaining_count(job_id)
        if remaining:
            await self.jobs.mark_paused(job_id)
            return BatchResult(
                job_id=job_id,
                status=JobStatus.PAUSED,
                processed_count=processed_count,
                fetched_count=fetched_count,
                failed_count=failed_count,
                recovered_count=recovered_count,
                remaining_count=remaining,
                stopped_reason="max_items",
            )
        return await self._finalize(
            job_id,
            processed_count,
            fetched_count,
            failed_count,
            recovered_count,
        )

    async def _recover_interrupted_items(self, job_id: str) -> int:
        interrupted = await self.items.list_by_status(job_id, ("fetching",))
        for item in interrupted:
            recovered = self.artifacts.load_valid_raw(job_id, item)
            if recovered is None:
                await self.items.reset_to_discovered(job_id, item.item_id)
                continue
            _, artifact_dir = recovered
            await self.items.mark_fetched(job_id, item.item_id, artifact_dir)
        return len(interrupted)

    async def _finalize(
        self,
        job_id: str,
        processed_count: int,
        fetched_count: int,
        failed_count: int,
        recovered_count: int,
    ) -> BatchResult:
        counts = await self.items.count_by_status(job_id)
        status = (
            JobStatus.COMPLETED_WITH_ERRORS
            if counts.get("retryable_failed", 0)
            else JobStatus.COMPLETED
        )
        await self.jobs.update_status(job_id, status.value)
        return BatchResult(
            job_id=job_id,
            status=status,
            processed_count=processed_count,
            fetched_count=fetched_count,
            failed_count=failed_count,
            recovered_count=recovered_count,
            remaining_count=0,
            stopped_reason="queue_empty",
        )

    async def _result(
        self,
        job_id: str,
        status: JobStatus,
        processed_count: int,
        fetched_count: int,
        failed_count: int,
        recovered_count: int,
        stopped_reason: str,
    ) -> BatchResult:
        return BatchResult(
            job_id=job_id,
            status=status,
            processed_count=processed_count,
            fetched_count=fetched_count,
            failed_count=failed_count,
            recovered_count=recovered_count,
            remaining_count=await self._remaining_count(job_id),
            stopped_reason=stopped_reason,
        )

    async def _remaining_count(self, job_id: str) -> int:
        counts = await self.items.count_by_status(job_id)
        return counts.get("discovered", 0) + counts.get("fetching", 0)
