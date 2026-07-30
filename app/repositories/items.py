import json
import sqlite3
from dataclasses import dataclass
from typing import cast

from app.models.discovery import DiscoveredItem
from app.repositories.database import Database


@dataclass(frozen=True)
class ItemCheckpoint:
    status: str
    attempt_count: int
    artifact_dir: str | None
    content_hash: str | None
    last_error_code: str | None
    snapshot_hash: str | None = None
    previous_snapshot_hash: str | None = None
    baseline_job_id: str | None = None
    change_status: str | None = None
    changed_components: tuple[str, ...] = ()
    checked_at: str | None = None


@dataclass(frozen=True)
class IncrementalBaseline:
    job_id: str
    item: DiscoveredItem
    snapshot_hash: str
    content_hash: str


class ItemRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def upsert_discovered(
        self,
        job_id: str,
        items: list[DiscoveredItem],
    ) -> int:
        if not items:
            return 0

        def upsert(connection: sqlite3.Connection) -> int:
            before = connection.total_changes
            connection.executemany(
                """
                INSERT INTO crawl_items(
                    job_id, item_id, source_url, canonical_url, title_hint,
                    discovery_page, status, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, 'discovered', datetime('now'))
                ON CONFLICT(job_id, item_id) DO UPDATE SET
                    source_url = excluded.source_url,
                    canonical_url = excluded.canonical_url,
                    title_hint = COALESCE(excluded.title_hint, crawl_items.title_hint),
                    discovery_page = excluded.discovery_page,
                    updated_at = excluded.updated_at
                """,
                [
                    (
                        job_id,
                        item.item_id,
                        str(item.source_url),
                        str(item.canonical_url),
                        item.title_hint,
                        str(item.discovery_page),
                    )
                    for item in items
                ],
            )
            return connection.total_changes - before

        return await self.database.execute_write(upsert)

    async def list_for_job(self, job_id: str) -> list[DiscoveredItem]:
        def select(connection: sqlite3.Connection) -> list[sqlite3.Row]:
            return connection.execute(
                """
                SELECT item_id, source_url, canonical_url, title_hint, discovery_page
                FROM crawl_items
                WHERE job_id = ?
                ORDER BY canonical_url
                """,
                (job_id,),
            ).fetchall()

        rows = await self.database.execute_read(select)
        return [
            DiscoveredItem(
                item_id=row["item_id"],
                source_url=row["source_url"],
                canonical_url=row["canonical_url"],
                title_hint=row["title_hint"],
                discovery_page=row["discovery_page"],
            )
            for row in rows
        ]

    async def mark_fetching(self, job_id: str, item_id: str) -> int:
        def update(connection: sqlite3.Connection) -> int:
            cursor = connection.execute(
                """
                UPDATE crawl_items
                SET status = 'fetching',
                    attempt_count = attempt_count + 1,
                    last_error_code = NULL,
                    updated_at = datetime('now')
                WHERE job_id = ? AND item_id = ?
                """,
                (job_id, item_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown crawl item: {job_id}/{item_id}")
            row = connection.execute(
                """
                SELECT attempt_count
                FROM crawl_items
                WHERE job_id = ? AND item_id = ?
                """,
                (job_id, item_id),
            ).fetchone()
            return int(row["attempt_count"])

        return await self.database.execute_write(update)

    async def mark_fetched(
        self,
        job_id: str,
        item_id: str,
        artifact_dir: str,
    ) -> None:
        def update(connection: sqlite3.Connection) -> None:
            cursor = connection.execute(
                """
                UPDATE crawl_items
                SET status = 'fetched',
                    artifact_dir = ?,
                    last_error_code = NULL,
                    updated_at = datetime('now')
                WHERE job_id = ? AND item_id = ?
                """,
                (artifact_dir, job_id, item_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown crawl item: {job_id}/{item_id}")

        await self.database.execute_write(update)

    async def mark_fetch_failed(
        self,
        job_id: str,
        item_id: str,
        error_code: str,
    ) -> None:
        def update(connection: sqlite3.Connection) -> None:
            cursor = connection.execute(
                """
                UPDATE crawl_items
                SET status = 'retryable_failed',
                    last_error_code = ?,
                    updated_at = datetime('now')
                WHERE job_id = ? AND item_id = ?
                """,
                (error_code, job_id, item_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown crawl item: {job_id}/{item_id}")

        await self.database.execute_write(update)

    async def get_checkpoint(
        self,
        job_id: str,
        item_id: str,
    ) -> ItemCheckpoint | None:
        def select(connection: sqlite3.Connection) -> sqlite3.Row | None:
            return cast(
                sqlite3.Row | None,
                connection.execute(
                    """
                    SELECT status, attempt_count, artifact_dir, content_hash,
                           last_error_code, snapshot_hash,
                           previous_snapshot_hash, baseline_job_id,
                           change_status, changed_components_json, checked_at
                    FROM crawl_items
                    WHERE job_id = ? AND item_id = ?
                    """,
                    (job_id, item_id),
                ).fetchone(),
            )

        row = await self.database.execute_read(select)
        if row is None:
            return None
        return ItemCheckpoint(
            status=row["status"],
            attempt_count=row["attempt_count"],
            artifact_dir=row["artifact_dir"],
            content_hash=row["content_hash"],
            last_error_code=row["last_error_code"],
            snapshot_hash=row["snapshot_hash"],
            previous_snapshot_hash=row["previous_snapshot_hash"],
            baseline_job_id=row["baseline_job_id"],
            change_status=row["change_status"],
            changed_components=tuple(
                json.loads(row["changed_components_json"] or "[]")
            ),
            checked_at=row["checked_at"],
        )

    async def find_incremental_baseline(
        self,
        *,
        job_id: str,
        item_id: str,
        plugin: str,
    ) -> IncrementalBaseline | None:
        def select(connection: sqlite3.Connection) -> sqlite3.Row | None:
            return cast(
                sqlite3.Row | None,
                connection.execute(
                    """
                    SELECT ci.job_id, ci.item_id, ci.source_url,
                           ci.canonical_url, ci.title_hint,
                           ci.discovery_page, ci.content_hash,
                           ci.snapshot_hash, ci.artifact_dir
                    FROM crawl_items AS ci
                    JOIN crawl_jobs AS cj ON cj.id = ci.job_id
                    WHERE ci.job_id <> ?
                      AND ci.item_id = ?
                      AND cj.plugin = ?
                      AND ci.status = 'parsed'
                      AND ci.snapshot_hash IS NOT NULL
                      AND ci.content_hash IS NOT NULL
                      AND ci.artifact_dir IS NOT NULL
                    ORDER BY cj.created_at DESC, ci.updated_at DESC
                    LIMIT 1
                    """,
                    (job_id, item_id, plugin),
                ).fetchone(),
            )

        row = await self.database.execute_read(select)
        if row is None:
            return None
        item = DiscoveredItem(
            item_id=row["item_id"],
            source_url=row["source_url"],
            canonical_url=row["canonical_url"],
            title_hint=row["title_hint"],
            discovery_page=row["discovery_page"],
        )
        return IncrementalBaseline(
            job_id=row["job_id"],
            item=item,
            snapshot_hash=row["snapshot_hash"],
            content_hash=row["content_hash"],
        )

    async def record_incremental(
        self,
        *,
        job_id: str,
        item_id: str,
        snapshot_hash: str,
        previous_snapshot_hash: str | None,
        baseline_job_id: str | None,
        change_status: str,
        changed_components: tuple[str, ...],
    ) -> None:
        def update(connection: sqlite3.Connection) -> None:
            cursor = connection.execute(
                """
                UPDATE crawl_items
                SET snapshot_hash = ?,
                    previous_snapshot_hash = ?,
                    previous_content_hash = (
                        SELECT content_hash
                        FROM crawl_items
                        WHERE job_id = ? AND item_id = ?
                    ),
                    baseline_job_id = ?,
                    change_status = ?,
                    changed_components_json = ?,
                    checked_at = datetime('now'),
                    updated_at = datetime('now')
                WHERE job_id = ? AND item_id = ?
                """,
                (
                    snapshot_hash,
                    previous_snapshot_hash,
                    baseline_job_id,
                    item_id,
                    baseline_job_id,
                    change_status,
                    json.dumps(changed_components),
                    job_id,
                    item_id,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown crawl item: {job_id}/{item_id}")

        await self.database.execute_write(update)

    async def list_by_status(
        self,
        job_id: str,
        statuses: tuple[str, ...],
    ) -> list[DiscoveredItem]:
        if not statuses:
            return []
        placeholders = ",".join("?" for _ in statuses)

        def select(connection: sqlite3.Connection) -> list[sqlite3.Row]:
            return connection.execute(
                f"""
                SELECT item_id, source_url, canonical_url, title_hint, discovery_page
                FROM crawl_items
                WHERE job_id = ? AND status IN ({placeholders})
                ORDER BY canonical_url
                """,  # noqa: S608
                (job_id, *statuses),
            ).fetchall()

        rows = await self.database.execute_read(select)
        return [
            DiscoveredItem(
                item_id=row["item_id"],
                source_url=row["source_url"],
                canonical_url=row["canonical_url"],
                title_hint=row["title_hint"],
                discovery_page=row["discovery_page"],
            )
            for row in rows
        ]

    async def select_next_discovered(
        self,
        job_id: str,
    ) -> DiscoveredItem | None:
        items = await self.list_by_status(job_id, ("discovered",))
        return items[0] if items else None

    async def reset_to_discovered(self, job_id: str, item_id: str) -> None:
        def update(connection: sqlite3.Connection) -> None:
            cursor = connection.execute(
                """
                UPDATE crawl_items
                SET status = 'discovered',
                    artifact_dir = NULL,
                    updated_at = datetime('now')
                WHERE job_id = ? AND item_id = ?
                """,
                (job_id, item_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown crawl item: {job_id}/{item_id}")

        await self.database.execute_write(update)

    async def count_by_status(self, job_id: str) -> dict[str, int]:
        def select(connection: sqlite3.Connection) -> list[sqlite3.Row]:
            return connection.execute(
                """
                SELECT status, COUNT(*) AS item_count
                FROM crawl_items
                WHERE job_id = ?
                GROUP BY status
                """,
                (job_id,),
            ).fetchall()

        return {
            str(row["status"]): int(row["item_count"])
            for row in await self.database.execute_read(select)
        }

    async def mark_cleaning(self, job_id: str, item_id: str) -> None:
        await self._update_clean_state(
            job_id,
            item_id,
            status="cleaning",
            content_hash=None,
            error_code=None,
        )

    async def mark_cleaned(
        self,
        job_id: str,
        item_id: str,
        content_hash: str,
        artifact_dir: str,
    ) -> None:
        def update(connection: sqlite3.Connection) -> None:
            cursor = connection.execute(
                """
                UPDATE crawl_items
                SET status = 'cleaned',
                    content_hash = ?,
                    artifact_dir = ?,
                    last_error_code = NULL,
                    updated_at = datetime('now')
                WHERE job_id = ? AND item_id = ?
                """,
                (content_hash, artifact_dir, job_id, item_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown crawl item: {job_id}/{item_id}")

        await self.database.execute_write(update)

    async def mark_clean_failed(
        self,
        job_id: str,
        item_id: str,
        error_code: str,
    ) -> None:
        await self._update_clean_state(
            job_id,
            item_id,
            status="retryable_failed",
            content_hash=None,
            error_code=error_code,
        )

    async def mark_parsing(self, job_id: str, item_id: str) -> None:
        await self._update_clean_state(
            job_id,
            item_id,
            status="parsing",
            content_hash=None,
            error_code=None,
        )

    async def mark_parsed(
        self,
        job_id: str,
        item_id: str,
        artifact_dir: str,
    ) -> None:
        def update(connection: sqlite3.Connection) -> None:
            cursor = connection.execute(
                """
                UPDATE crawl_items
                SET status = 'parsed',
                    artifact_dir = ?,
                    last_error_code = NULL,
                    updated_at = datetime('now')
                WHERE job_id = ? AND item_id = ?
                """,
                (artifact_dir, job_id, item_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown crawl item: {job_id}/{item_id}")

        await self.database.execute_write(update)

    async def mark_parse_failed(
        self,
        job_id: str,
        item_id: str,
        error_code: str,
    ) -> None:
        await self._update_clean_state(
            job_id,
            item_id,
            status="retryable_failed",
            content_hash=None,
            error_code=error_code,
        )

    async def _update_clean_state(
        self,
        job_id: str,
        item_id: str,
        *,
        status: str,
        content_hash: str | None,
        error_code: str | None,
    ) -> None:
        def update(connection: sqlite3.Connection) -> None:
            cursor = connection.execute(
                """
                UPDATE crawl_items
                SET status = ?,
                    content_hash = COALESCE(?, content_hash),
                    last_error_code = ?,
                    updated_at = datetime('now')
                WHERE job_id = ? AND item_id = ?
                """,
                (status, content_hash, error_code, job_id, item_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown crawl item: {job_id}/{item_id}")

        await self.database.execute_write(update)
