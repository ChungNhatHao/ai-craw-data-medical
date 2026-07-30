import sqlite3
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

from app.models.crawl import CrawlJob, JobStatus
from app.repositories.database import Database


class JobRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def create(self, plugin: str) -> CrawlJob:
        job = CrawlJob(id=uuid4(), plugin=plugin)

        def insert(connection: sqlite3.Connection) -> None:
            connection.execute(
                """
                INSERT INTO crawl_jobs(id, plugin, status, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (str(job.id), job.plugin, job.status.value, job.created_at.isoformat()),
            )

        await self.database.execute_write(insert)
        return job

    async def update_status(self, job_id: str, status: str) -> None:
        parsed_status = JobStatus(status)
        now = datetime.now(UTC).isoformat()

        def update(connection: sqlite3.Connection) -> None:
            cursor = connection.execute(
                """
                UPDATE crawl_jobs
                SET status = ?,
                    started_at = CASE
                        WHEN ? = 'running' AND started_at IS NULL THEN ?
                        ELSE started_at
                    END,
                    finished_at = CASE
                        WHEN ? IN (
                            'completed', 'completed_with_errors', 'failed', 'cancelled'
                        ) THEN ?
                        ELSE finished_at
                    END
                WHERE id = ?
                """,
                (parsed_status.value, parsed_status.value, now, parsed_status.value, now, job_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown job: {job_id}")

        await self.database.execute_write(update)

    async def get(self, job_id: str | UUID) -> CrawlJob | None:
        def select(connection: sqlite3.Connection) -> sqlite3.Row | None:
            return cast(
                sqlite3.Row | None,
                connection.execute(
                    "SELECT * FROM crawl_jobs WHERE id = ?",
                    (str(job_id),),
                ).fetchone(),
            )

        row = await self.database.execute_read(select)
        if row is None:
            return None
        return CrawlJob(
            id=UUID(row["id"]),
            plugin=row["plugin"],
            status=JobStatus(row["status"]),
            created_at=row["created_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )

    async def request_pause(self, job_id: str) -> None:
        def update(connection: sqlite3.Connection) -> None:
            cursor = connection.execute(
                """
                UPDATE crawl_jobs
                SET stop_requested = 1,
                    status = CASE
                        WHEN status = 'running' THEN 'pausing'
                        ELSE status
                    END
                WHERE id = ?
                  AND status IN ('created', 'running', 'pausing', 'paused')
                """,
                (job_id,),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Job cannot be paused: {job_id}")

        await self.database.execute_write(update)

    async def is_stop_requested(self, job_id: str) -> bool:
        def select(connection: sqlite3.Connection) -> sqlite3.Row | None:
            return cast(
                sqlite3.Row | None,
                connection.execute(
                    "SELECT stop_requested FROM crawl_jobs WHERE id = ?",
                    (job_id,),
                ).fetchone(),
            )

        row = await self.database.execute_read(select)
        if row is None:
            raise KeyError(f"Unknown job: {job_id}")
        return bool(row["stop_requested"])

    async def mark_paused(self, job_id: str) -> None:
        await self.update_status(job_id, JobStatus.PAUSED.value)

    async def resume(self, job_id: str) -> None:
        now = datetime.now(UTC).isoformat()

        def update(connection: sqlite3.Connection) -> None:
            cursor = connection.execute(
                """
                UPDATE crawl_jobs
                SET stop_requested = 0,
                    status = 'running',
                    started_at = COALESCE(started_at, ?),
                    finished_at = NULL
                WHERE id = ?
                  AND status IN ('created', 'paused', 'pausing', 'running')
                """,
                (now, job_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Job cannot be resumed: {job_id}")

        await self.database.execute_write(update)
