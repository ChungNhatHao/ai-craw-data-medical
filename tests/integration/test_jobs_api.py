import asyncio

from httpx import ASGITransport, AsyncClient

from app.api.application import create_app
from app.core.config import Settings
from app.models.crawl import JobStatus
from app.repositories.agent_audit import AgentAuditRepository
from app.repositories.items import ItemRepository
from app.repositories.jobs import JobRepository
from app.services.reporting import ReportingService
from app.storage.artifacts import ArtifactStore


def test_job_create_status_and_missing_report_api(settings: Settings) -> None:
    async def scenario() -> None:
        app = create_app(settings)
        transport = ASGITransport(app=app)
        async with app.router.lifespan_context(app):
            async with AsyncClient(
                transport=transport,
                base_url="http://test",
            ) as client:
                created = await client.post(
                    "/api/v1/jobs",
                    json={"plugin": "fake"},
                )
                assert created.status_code == 201
                job_id = created.json()["id"]

                current = await client.get(f"/api/v1/jobs/{job_id}")
                missing_report = await client.get(
                    f"/api/v1/jobs/{job_id}/report"
                )
                jobs = JobRepository(app.state.database)
                await jobs.update_status(job_id, JobStatus.COMPLETED.value)
                await ReportingService(
                    jobs=jobs,
                    items=ItemRepository(app.state.database),
                    artifacts=ArtifactStore(settings.output_root),
                ).generate(job_id)
                report = await client.get(f"/api/v1/jobs/{job_id}/report")
                await AgentAuditRepository(
                    app.state.database
                ).record_decision(
                    job_id=job_id,
                    agent_name="navigation",
                    decision={"action": "open_candidate"},
                    confidence=0.9,
                )
                agent_trace = await client.get(
                    f"/api/v1/jobs/{job_id}/agent-trace"
                )
                finalized = await client.get(f"/api/v1/jobs/{job_id}")
                unknown = await client.get(
                    "/api/v1/jobs/00000000-0000-0000-0000-000000000000"
                )

        assert current.status_code == 200
        assert current.json()["job"]["status"] == "created"
        assert current.json()["counts"] == {}
        assert current.json()["report_available"] is False
        assert missing_report.status_code == 404
        assert report.status_code == 200
        assert report.json()["job_id"] == job_id
        assert agent_trace.status_code == 200
        assert agent_trace.json()["decision_count"] == 1
        assert agent_trace.json()["decisions"][0]["agent_name"] == "navigation"
        assert finalized.json()["report_available"] is True
        assert unknown.status_code == 404

    asyncio.run(scenario())
