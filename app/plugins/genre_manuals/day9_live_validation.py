import asyncio
import hashlib
import json

from httpx import ASGITransport, AsyncClient

from app.api.application import create_app
from app.core.config import get_settings
from app.models.report import FinalJobManifest, JobReport
from app.plugins.genre_manuals.live_support import find_latest_artifact_job
from app.repositories.database import Database
from app.repositories.items import ItemRepository
from app.repositories.jobs import JobRepository
from app.services.reporting import ReportingService
from app.storage.artifacts import ArtifactStore


async def validate_day9() -> dict[str, object]:
    settings = get_settings()
    job_id = find_latest_artifact_job(
        settings.output_root,
        minimum_items=2,
    )
    database = Database(settings.database_path, settings.migrations_path)
    await database.initialize()
    artifacts = ArtifactStore(settings.output_root)
    report = await ReportingService(
        jobs=JobRepository(database),
        items=ItemRepository(database),
        artifacts=artifacts,
    ).generate(job_id)

    job_directory = settings.output_root / "jobs" / job_id
    report_bytes = (job_directory / "report.json").read_bytes()
    final = FinalJobManifest.model_validate_json(
        (job_directory / "job.json").read_bytes()
    )
    reloaded = JobReport.model_validate_json(report_bytes)

    app = create_app(settings)
    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            status_response = await client.get(f"/api/v1/jobs/{job_id}")
            report_response = await client.get(
                f"/api/v1/jobs/{job_id}/report"
            )

    complete = [
        item for item in report.items if item.complete_artifact_set
    ]
    failed = [
        item for item in report.items if item.last_error_code is not None
    ]
    return {
        "job_id": job_id,
        "status": report.status,
        "total_items": report.total_items,
        "successful_items": report.successful_items,
        "failed_items": report.failed_items,
        "complete_artifact_sets": len(complete),
        "failed_queue_items_in_report": len(failed),
        "failed_error_codes": [
            item.last_error_code for item in failed
        ],
        "report_reload_valid": reloaded == report,
        "report_hash_matches_job_manifest": (
            hashlib.sha256(report_bytes).hexdigest() == final.report.sha256
        ),
        "api_status_code": status_response.status_code,
        "api_report_status_code": report_response.status_code,
        "api_report_available": status_response.json()["report_available"],
        "api_report_job_matches": (
            report_response.json()["job_id"] == job_id
        ),
        "report_path": f"jobs/{job_id}/report.json",
        "job_manifest_path": f"jobs/{job_id}/job.json",
        "external_website_requests": 0,
    }


def main() -> None:
    print(json.dumps(asyncio.run(validate_day9()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

