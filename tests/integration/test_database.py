import asyncio

from app.core.config import Settings
from app.models.crawl import JobStatus
from app.repositories.database import Database
from app.repositories.jobs import JobRepository


def test_database_migration_and_job_lifecycle(settings: Settings) -> None:
    async def scenario() -> None:
        settings.ensure_directories()
        database = Database(settings.database_path, settings.migrations_path)
        await database.initialize()
        assert await database.ping()

        repository = JobRepository(database)
        created = await repository.create("fake")
        assert created.status is JobStatus.CREATED

        await repository.update_status(str(created.id), "running")
        await repository.update_status(str(created.id), "completed")
        completed = await repository.get(created.id)

        assert completed is not None
        assert completed.status is JobStatus.COMPLETED
        assert completed.started_at is not None
        assert completed.finished_at is not None

    asyncio.run(scenario())

