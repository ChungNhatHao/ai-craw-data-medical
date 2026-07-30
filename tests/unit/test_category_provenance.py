import asyncio
from pathlib import Path

from app.models.category import CategoryItemProvenance
from app.models.discovery import DiscoveredItem
from app.repositories.category_provenance import CategoryProvenanceRepository
from app.repositories.database import Database
from app.repositories.items import ItemRepository
from app.repositories.jobs import JobRepository


def test_provenance_keeps_multiple_roots_and_paths_for_one_item(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        database = Database(
            tmp_path / "crawler.db",
            Path("migrations"),
        )
        await database.initialize()
        job = await JobRepository(database).create("fake")
        job_id = str(job.id)
        item_id = "a" * 64
        item = DiscoveredItem(
            item_id=item_id,
            source_url="https://example.test/atrial-fibrillation",
            canonical_url="https://example.test/atrial-fibrillation",
            title_hint="Atrial fibrillation",
            discovery_page="https://example.test/search",
        )
        await ItemRepository(database).upsert_discovered(job_id, [item])

        repository = CategoryProvenanceRepository(database)
        records = [
            CategoryItemProvenance(
                job_id=job_id,
                item_id=item_id,
                root_query="Cardiac arrhythmia",
                parent_url="https://example.test/cardiac-arrhythmias",
                menu_path=("Cardiac arrhythmias", "Atrial fibrillation"),
                depth=1,
            ),
            CategoryItemProvenance(
                job_id=job_id,
                item_id=item_id,
                root_query="Heart rhythm disorders",
                parent_url="https://example.test/heart-rhythm",
                menu_path=("Heart rhythm disorders", "Atrial fibrillation"),
                depth=1,
            ),
            CategoryItemProvenance(
                job_id=job_id,
                item_id=item_id,
                root_query="Cardiac arrhythmia",
                parent_url="https://example.test/arrhythmia-a-z",
                menu_path=(
                    "Cardiac arrhythmias",
                    "Arrhythmia A-Z",
                    "Atrial fibrillation",
                ),
                depth=2,
            ),
        ]

        assert await repository.upsert_many(records) == 3
        by_item = await repository.list_for_item(job_id, item_id)
        by_job = await repository.list_for_job(job_id)

        assert len(by_item) == 3
        assert by_job == {item_id: by_item}
        assert {record.root_query for record in by_item} == {
            "Cardiac arrhythmia",
            "Heart rhythm disorders",
        }
        assert {
            record.menu_path for record in by_item
        } == {record.menu_path for record in records}
        assert all(record.created_at is not None for record in by_item)

        # Replaying one path updates it without collapsing the other paths.
        assert await repository.upsert_many([records[0]]) == 1
        assert len(await repository.list_for_item(job_id, item_id)) == 3

    asyncio.run(scenario())
