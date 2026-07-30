import json
import sqlite3
from datetime import UTC, datetime

from app.models.category import CategoryItemProvenance
from app.repositories.database import Database


class CategoryProvenanceRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def upsert_many(
        self,
        provenance: list[CategoryItemProvenance],
    ) -> int:
        if not provenance:
            return 0
        now = datetime.now(UTC).isoformat()

        def upsert(connection: sqlite3.Connection) -> int:
            before = connection.total_changes
            connection.executemany(
                """
                INSERT INTO category_item_provenance(
                    job_id, item_id, root_query, parent_url, menu_path_json,
                    depth, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id, item_id, root_query, menu_path_json)
                DO UPDATE SET
                    parent_url = excluded.parent_url,
                    depth = excluded.depth,
                    updated_at = excluded.updated_at
                """,
                [
                    (
                        record.job_id,
                        record.item_id,
                        record.root_query,
                        str(record.parent_url) if record.parent_url else None,
                        _encode_path(record.menu_path),
                        record.depth,
                        now,
                        now,
                    )
                    for record in provenance
                ],
            )
            return connection.total_changes - before

        return await self.database.execute_write(upsert)

    async def list_for_item(
        self,
        job_id: str,
        item_id: str,
    ) -> tuple[CategoryItemProvenance, ...]:
        def select(connection: sqlite3.Connection) -> list[sqlite3.Row]:
            return connection.execute(
                """
                SELECT job_id, item_id, root_query, parent_url, menu_path_json,
                       depth, created_at, updated_at
                FROM category_item_provenance
                WHERE job_id = ? AND item_id = ?
                ORDER BY root_query COLLATE NOCASE, menu_path_json
                """,
                (job_id, item_id),
            ).fetchall()

        return _decode_rows(await self.database.execute_read(select))

    async def list_for_job(
        self,
        job_id: str,
    ) -> dict[str, tuple[CategoryItemProvenance, ...]]:
        def select(connection: sqlite3.Connection) -> list[sqlite3.Row]:
            return connection.execute(
                """
                SELECT job_id, item_id, root_query, parent_url, menu_path_json,
                       depth, created_at, updated_at
                FROM category_item_provenance
                WHERE job_id = ?
                ORDER BY item_id, root_query COLLATE NOCASE, menu_path_json
                """,
                (job_id,),
            ).fetchall()

        grouped: dict[str, list[CategoryItemProvenance]] = {}
        for record in _decode_rows(await self.database.execute_read(select)):
            grouped.setdefault(record.item_id, []).append(record)
        return {
            item_id: tuple(records)
            for item_id, records in grouped.items()
        }


def _encode_path(menu_path: tuple[str, ...]) -> str:
    return json.dumps(
        menu_path,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _decode_rows(
    rows: list[sqlite3.Row],
) -> tuple[CategoryItemProvenance, ...]:
    return tuple(
        CategoryItemProvenance(
            job_id=row["job_id"],
            item_id=row["item_id"],
            root_query=row["root_query"],
            parent_url=row["parent_url"],
            menu_path=tuple(json.loads(row["menu_path_json"])),
            depth=row["depth"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        for row in rows
    )
