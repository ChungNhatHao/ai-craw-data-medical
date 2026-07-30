import sqlite3
from datetime import UTC, datetime

from app.models.attempts import CrawlAttempt
from app.repositories.database import Database


class AttemptRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def start(
        self,
        job_id: str,
        item_id: str,
        attempt_no: int,
        stage: str,
    ) -> int:
        started_at = datetime.now(UTC).isoformat()

        def insert(connection: sqlite3.Connection) -> int:
            cursor = connection.execute(
                """
                INSERT INTO crawl_attempts(
                    job_id, item_id, attempt_no, stage, started_at, result
                )
                VALUES (?, ?, ?, ?, ?, 'running')
                """,
                (job_id, item_id, attempt_no, stage, started_at),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("SQLite did not return an attempt ID")
            return cursor.lastrowid

        return await self.database.execute_write(insert)

    async def finish(
        self,
        attempt_id: int,
        *,
        result: str,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        finished_at = datetime.now(UTC).isoformat()

        def update(connection: sqlite3.Connection) -> None:
            cursor = connection.execute(
                """
                UPDATE crawl_attempts
                SET finished_at = ?, result = ?, error_code = ?, error_message = ?
                WHERE id = ?
                """,
                (
                    finished_at,
                    result,
                    error_code,
                    error_message,
                    attempt_id,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown crawl attempt: {attempt_id}")

        await self.database.execute_write(update)

    async def list_for_item(self, job_id: str, item_id: str) -> list[CrawlAttempt]:
        def select(connection: sqlite3.Connection) -> list[sqlite3.Row]:
            return connection.execute(
                """
                SELECT id, job_id, item_id, attempt_no, stage, started_at,
                       finished_at, result, error_code, error_message
                FROM crawl_attempts
                WHERE job_id = ? AND item_id = ?
                ORDER BY attempt_no, id
                """,
                (job_id, item_id),
            ).fetchall()

        return [
            CrawlAttempt(
                id=row["id"],
                job_id=row["job_id"],
                item_id=row["item_id"],
                attempt_no=row["attempt_no"],
                stage=row["stage"],
                started_at=row["started_at"],
                finished_at=row["finished_at"],
                result=row["result"],
                error_code=row["error_code"],
                error_message=row["error_message"],
            )
            for row in await self.database.execute_read(select)
        ]

    async def next_attempt_no(
        self,
        job_id: str,
        item_id: str,
        stage: str,
    ) -> int:
        def select(connection: sqlite3.Connection) -> int:
            row = connection.execute(
                """
                SELECT COALESCE(MAX(attempt_no), 0) + 1 AS next_attempt
                FROM crawl_attempts
                WHERE job_id = ? AND item_id = ? AND stage = ?
                """,
                (job_id, item_id, stage),
            ).fetchone()
            return int(row["next_attempt"])

        return await self.database.execute_read(select)
