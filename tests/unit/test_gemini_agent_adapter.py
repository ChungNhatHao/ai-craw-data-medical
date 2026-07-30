import asyncio

import pytest
from pydantic import BaseModel

from app.ai.agent_adapter import AgentModelPolicy, GeminiAgentAdapter
from app.ai.client import GeminiClient
from app.ai.protocol import GeminiTransportResponse, GeminiUsage
from app.core.config import Settings
from app.core.errors import CrawlerError, ErrorCode
from app.models.agentic import NavigationDecision
from app.repositories.agent_audit import AgentAuditRepository
from app.repositories.database import Database
from app.repositories.jobs import JobRepository


class FakeTransport:
    async def generate_structured(
        self,
        *,
        model: str,
        prompt: str,
        response_schema: type[BaseModel],
        temperature: float,
    ) -> GeminiTransportResponse:
        del prompt, response_schema, temperature
        assert model == "navigation-model"
        return GeminiTransportResponse(
            parsed={
                "action": "stop",
                "candidate_id": None,
                "confidence": 0.9,
                "reason_code": "no_candidate",
            },
            usage=GeminiUsage(input_tokens=10, output_tokens=5),
            model_version="fake",
        )


def test_gemini_agent_adapter_audits_and_enforces_budget(
    settings: Settings,
) -> None:
    async def scenario() -> None:
        settings.ensure_directories()
        database = Database(settings.database_path, settings.migrations_path)
        await database.initialize()
        job = await JobRepository(database).create("genre_manuals")
        audit = AgentAuditRepository(database)
        adapter = GeminiAgentAdapter(
            client=GeminiClient(
                transport=FakeTransport(),  # type: ignore[arg-type]
                max_retries=0,
            ),
            models=AgentModelPolicy(
                navigation="navigation-model",
                disease_detector="detector-model",
                disease_extraction="extraction-model",
                normalization="normalization-model",
            ),
            audit=audit,
            job_id=str(job.id),
            max_calls=1,
        )

        decision = await adapter.generate_structured(
            agent_name="navigation",
            prompt="Choose safely",
            payload={"prompt_version": "1.0.0", "links": []},
            response_model=NavigationDecision,
        )

        assert decision.action == "stop"
        calls = await audit.list_model_calls(str(job.id))
        assert len(calls) == 1
        assert calls[0].input_tokens == 10
        with pytest.raises(CrawlerError) as captured:
            await adapter.generate_structured(
                agent_name="navigation",
                prompt="Choose safely",
                payload={"prompt_version": "1.0.0", "links": []},
                response_model=NavigationDecision,
            )
        assert captured.value.code is ErrorCode.AGENT_BUDGET_EXHAUSTED

    asyncio.run(scenario())
