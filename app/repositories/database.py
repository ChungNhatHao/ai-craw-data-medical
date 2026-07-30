import asyncio
import sqlite3
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import TypeVar, cast

T = TypeVar("T")


class Database:
    def __init__(self, path: Path, migrations_path: Path) -> None:
        self.path = path
        self.migrations_path = migrations_path
        self._write_lock = asyncio.Lock()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_sync()

    def _initialize_sync(self) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        name TEXT PRIMARY KEY,
                        applied_at TEXT NOT NULL
                    )
                    """
                )
                applied = {
                    row["name"]
                    for row in connection.execute("SELECT name FROM schema_migrations").fetchall()
                }
                for migration in sorted(self.migrations_path.glob("*.sql")):
                    if migration.name in applied:
                        continue
                    connection.executescript(migration.read_text(encoding="utf-8"))
                    connection.execute(
                        """
                        INSERT INTO schema_migrations(name, applied_at)
                        VALUES (?, datetime('now'))
                        """,
                        (migration.name,),
                    )

    async def execute_write(
        self,
        operation: Callable[[sqlite3.Connection], T],
    ) -> T:
        async with self._write_lock:
            return self._run(operation)

    async def execute_read(
        self,
        operation: Callable[[sqlite3.Connection], T],
    ) -> T:
        return self._run(operation)

    def _run(self, operation: Callable[[sqlite3.Connection], T]) -> T:
        with closing(self._connect()) as connection:
            with connection:
                return operation(connection)

    async def ping(self) -> bool:
        try:
            result = cast(
                int,
                await self.execute_read(
                    lambda connection: connection.execute("SELECT 1").fetchone()[0]
                ),
            )
            return result == 1
        except sqlite3.Error:
            return False
