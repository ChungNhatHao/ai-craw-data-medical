import asyncio

from app.agents.graph import build_demo_graph
from app.core.config import Settings
from app.models.crawl import JobStatus
from app.plugins.fake import FakeSitePlugin
from app.repositories.database import Database
from app.repositories.jobs import JobRepository


def test_demo_graph_completes_fake_job(settings: Settings) -> None:
    async def scenario() -> None:
        settings.ensure_directories()
        database = Database(settings.database_path, settings.migrations_path)
        await database.initialize()
        jobs = JobRepository(database)
        job = await jobs.create("fake")

        graph = build_demo_graph(FakeSitePlugin(), jobs)
        result = await graph.ainvoke(
            {
                "job_id": str(job.id),
                "plugin_name": "fake",
                "status": "created",
                "discovered_count": 0,
                "error": None,
            }
        )

        persisted = await jobs.get(job.id)
        assert result["status"] == "completed"
        assert result["discovered_count"] == 2
        assert persisted is not None
        assert persisted.status is JobStatus.COMPLETED

    asyncio.run(scenario())

