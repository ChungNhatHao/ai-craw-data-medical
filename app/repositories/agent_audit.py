import json
import sqlite3
from datetime import UTC, datetime

from app.models.agent_audit import AgentDecisionRecord, ModelCallRecord
from app.repositories.database import Database


class AgentAuditRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def record_decision(
        self,
        *,
        job_id: str,
        agent_name: str,
        decision: dict[str, object],
        item_id: str | None = None,
        page_fingerprint: str | None = None,
        confidence: float | None = None,
    ) -> int:
        created_at = datetime.now(UTC).isoformat()
        payload = json.dumps(
            decision,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

        def insert(connection: sqlite3.Connection) -> int:
            cursor = connection.execute(
                """
                INSERT INTO agent_decisions(
                    job_id, item_id, agent_name, page_fingerprint,
                    decision_json, confidence, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    item_id,
                    agent_name,
                    page_fingerprint,
                    payload,
                    confidence,
                    created_at,
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("SQLite did not return an agent decision ID")
            return cursor.lastrowid

        return await self.database.execute_write(insert)

    async def record_model_call(
        self,
        *,
        job_id: str,
        agent_name: str,
        model_id: str,
        prompt_version: str,
        input_hash: str,
        latency_ms: int,
        status: str,
        item_id: str | None = None,
        output_hash: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cached: bool = False,
        error_code: str | None = None,
    ) -> int:
        created_at = datetime.now(UTC).isoformat()

        def insert(connection: sqlite3.Connection) -> int:
            cursor = connection.execute(
                """
                INSERT INTO model_calls(
                    job_id, item_id, agent_name, model_id, prompt_version,
                    input_hash, output_hash, latency_ms, input_tokens,
                    output_tokens, cached, status, error_code, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    item_id,
                    agent_name,
                    model_id,
                    prompt_version,
                    input_hash,
                    output_hash,
                    latency_ms,
                    input_tokens,
                    output_tokens,
                    int(cached),
                    status,
                    error_code,
                    created_at,
                ),
            )
            if cursor.lastrowid is None:
                raise RuntimeError("SQLite did not return a model call ID")
            return cursor.lastrowid

        return await self.database.execute_write(insert)

    async def list_decisions(self, job_id: str) -> list[AgentDecisionRecord]:
        def select(connection: sqlite3.Connection) -> list[sqlite3.Row]:
            return connection.execute(
                """
                SELECT id, job_id, item_id, agent_name, page_fingerprint,
                       decision_json, confidence, created_at
                FROM agent_decisions
                WHERE job_id = ?
                ORDER BY id
                """,
                (job_id,),
            ).fetchall()

        rows = await self.database.execute_read(select)
        return [
            AgentDecisionRecord(
                id=row["id"],
                job_id=row["job_id"],
                item_id=row["item_id"],
                agent_name=row["agent_name"],
                page_fingerprint=row["page_fingerprint"],
                decision=json.loads(row["decision_json"]),
                confidence=row["confidence"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    async def list_model_calls(self, job_id: str) -> list[ModelCallRecord]:
        def select(connection: sqlite3.Connection) -> list[sqlite3.Row]:
            return connection.execute(
                """
                SELECT id, job_id, item_id, agent_name, model_id,
                       prompt_version, input_hash, output_hash, latency_ms,
                       input_tokens, output_tokens, cached, status, error_code,
                       created_at
                FROM model_calls
                WHERE job_id = ?
                ORDER BY id
                """,
                (job_id,),
            ).fetchall()

        rows = await self.database.execute_read(select)
        return [
            ModelCallRecord(
                id=row["id"],
                job_id=row["job_id"],
                item_id=row["item_id"],
                agent_name=row["agent_name"],
                model_id=row["model_id"],
                prompt_version=row["prompt_version"],
                input_hash=row["input_hash"],
                output_hash=row["output_hash"],
                latency_ms=row["latency_ms"],
                input_tokens=row["input_tokens"],
                output_tokens=row["output_tokens"],
                cached=bool(row["cached"]),
                status=row["status"],
                error_code=row["error_code"],
                created_at=row["created_at"],
            )
            for row in rows
        ]
