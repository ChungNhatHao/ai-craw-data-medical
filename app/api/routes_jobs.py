from typing import Literal, cast
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from app.models.crawl import CrawlJob
from app.models.report import JobReport, JobStatusResponse
from app.models.run import RunRequest, RunSnapshot, RunStartResponse
from app.repositories.agent_audit import AgentAuditRepository
from app.repositories.items import ItemRepository
from app.repositories.jobs import JobRepository
from app.services.run_manager import RunManager
from app.services.xlsx_import import (
    build_disease_import_template,
    parse_disease_names_xlsx,
)
from app.storage.artifacts import ArtifactStore

router = APIRouter(prefix="/jobs", tags=["jobs"])
SAFE_ARTIFACT_FILES = frozenset(
    {
        "manifest.json",
        "raw.html",
        "tabs-raw.json",
        "tabs.json",
        "content.html",
        "markdown.md",
        "disease.json",
        "disease-decision.json",
        "disease-draft.json",
        "normalization.json",
        "screenshot.png",
    }
)
SAFE_JOB_ARTIFACT_FILES = frozenset(
    {
        "ai-discovery.json",
        "category-expansion.json",
        "disease-list.json",
        "import-search.json",
        "report.json",
    }
)


class CreateJobRequest(BaseModel):
    plugin: Literal["genre_manuals", "fake"] = "genre_manuals"


class XlsxImportPreview(BaseModel):
    disease_names: tuple[str, ...]
    count: int


@router.get("/imports/xlsx/template")
async def download_xlsx_template() -> Response:
    return Response(
        content=build_disease_import_template(),
        media_type=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition": (
                'attachment; filename="disease-import-template.xlsx"'
            )
        },
    )


@router.post("/imports/xlsx/parse", response_model=XlsxImportPreview)
async def parse_xlsx_import(request: Request) -> XlsxImportPreview:
    try:
        names = parse_disease_names_xlsx(await request.body())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return XlsxImportPreview(disease_names=names, count=len(names))


@router.post("", response_model=CrawlJob, status_code=status.HTTP_201_CREATED)
async def create_job(payload: CreateJobRequest, request: Request) -> CrawlJob:
    return await JobRepository(request.app.state.database).create(payload.plugin)


@router.get("/{job_id}", response_model=JobStatusResponse)
async def get_job(job_id: UUID, request: Request) -> JobStatusResponse:
    value = str(job_id)
    job = await JobRepository(request.app.state.database).get(value)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    counts = await ItemRepository(request.app.state.database).count_by_status(value)
    artifacts = ArtifactStore(request.app.state.settings.output_root)
    return JobStatusResponse(
        job=job,
        counts=counts,
        report_available=artifacts.has_job_report(value),
    )


@router.get("/{job_id}/report", response_model=JobReport)
async def get_job_report(job_id: UUID, request: Request) -> JobReport:
    value = str(job_id)
    if await JobRepository(request.app.state.database).get(value) is None:
        raise HTTPException(status_code=404, detail="Job not found")
    report = ArtifactStore(request.app.state.settings.output_root).load_job_report(value)
    if report is None:
        raise HTTPException(status_code=404, detail="Job report is not available")
    return report


@router.post(
    "/runs/start",
    response_model=RunStartResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_run(payload: RunRequest, request: Request) -> RunStartResponse:
    manager = cast(RunManager, request.app.state.run_manager)
    try:
        return await manager.start(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/runs/{job_id}", response_model=RunSnapshot)
async def get_run(job_id: UUID, request: Request) -> RunSnapshot:
    manager = cast(RunManager, request.app.state.run_manager)
    snapshot = await manager.get(str(job_id))
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return snapshot


@router.get("/{job_id}/artifacts/{file_name}")
async def download_job_artifact(
    job_id: UUID,
    file_name: str,
    request: Request,
) -> FileResponse:
    if file_name not in SAFE_JOB_ARTIFACT_FILES:
        raise HTTPException(status_code=404, detail="Artifact not found")
    value = str(job_id)
    if await JobRepository(request.app.state.database).get(value) is None:
        raise HTTPException(status_code=404, detail="Job not found")
    path = request.app.state.settings.output_root / "jobs" / value / file_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    return FileResponse(path, filename=f"{value[:8]}-{file_name}")


@router.get("/{job_id}/agent-trace")
async def get_agent_trace(job_id: UUID, request: Request) -> dict[str, object]:
    value = str(job_id)
    if await JobRepository(request.app.state.database).get(value) is None:
        raise HTTPException(status_code=404, detail="Job not found")
    repository = AgentAuditRepository(request.app.state.database)
    decisions = await repository.list_decisions(value)
    calls = await repository.list_model_calls(value)
    return {
        "job_id": value,
        "decision_count": len(decisions),
        "model_call_count": len(calls),
        "decisions": [
            decision.model_dump(mode="json") for decision in decisions
        ],
        "model_calls": [call.model_dump(mode="json") for call in calls],
    }


@router.get("/{job_id}/items/{item_id}/artifacts/{file_name}")
async def download_artifact(
    job_id: UUID,
    item_id: str,
    file_name: str,
    request: Request,
) -> FileResponse:
    if file_name not in SAFE_ARTIFACT_FILES:
        raise HTTPException(status_code=404, detail="Artifact not found")
    value = str(job_id)
    items = ItemRepository(request.app.state.database)
    discovered = await items.list_for_job(value)
    item = next(
        (candidate for candidate in discovered if candidate.item_id == item_id),
        None,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    directory, _ = ArtifactStore(
        request.app.state.settings.output_root
    ).item_directory(value, item)
    path = directory / file_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    return FileResponse(path, filename=f"{item.item_id[:12]}-{file_name}")
