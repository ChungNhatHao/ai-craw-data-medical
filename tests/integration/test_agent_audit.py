import asyncio

from app.core.config import Settings
from app.repositories.agent_audit import AgentAuditRepository
from app.repositories.database import Database
from app.repositories.jobs import JobRepository

HASH = "a" * 64


def test_agent_decisions_and_model_calls_are_auditable(
    settings: Settings,
) -> None:
    async def scenario() -> None:
        settings.ensure_directories()
        database = Database(settings.database_path, settings.migrations_path)
        await database.initialize()
        job = await JobRepository(database).create("genre_manuals")
        repository = AgentAuditRepository(database)

        await repository.record_decision(
            job_id=str(job.id),
            agent_name="disease_detector",
            page_fingerprint=HASH,
            decision={"is_disease_detail": True, "reason": "confirmed"},
            confidence=0.96,
        )
        await repository.record_model_call(
            job_id=str(job.id),
            agent_name="disease_detector",
            model_id="fake-gemini",
            prompt_version="1.0.0",
            input_hash=HASH,
            output_hash="b" * 64,
            latency_ms=42,
            input_tokens=100,
            output_tokens=20,
            status="success",
        )

        decisions = await repository.list_decisions(str(job.id))
        calls = await repository.list_model_calls(str(job.id))

        assert len(decisions) == 1
        assert decisions[0].decision["is_disease_detail"] is True
        assert decisions[0].confidence == 0.96
        assert len(calls) == 1
        assert calls[0].input_hash == HASH
        assert calls[0].input_tokens == 100
        assert calls[0].cached is False

    asyncio.run(scenario())
