from typing import Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel

router = APIRouter(prefix="/health", tags=["health"])


class LiveResponse(BaseModel):
    status: Literal["ok"]


class ReadyResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    database: Literal["ok", "error"]
    artifact_store: Literal["ok", "error"]
    gemini_agentic: Literal["ready", "disabled", "misconfigured"]
    agentic_discovery_enabled: bool
    agentic_parsing_enabled: bool
    ai_normalization_enabled: bool


@router.get("/live", response_model=LiveResponse)
async def live() -> LiveResponse:
    return LiveResponse(status="ok")


@router.get("/ready", response_model=ReadyResponse)
async def ready(request: Request, response: Response) -> ReadyResponse:
    database_ok = await request.app.state.database.ping()
    artifact_ok = request.app.state.settings.output_root.is_dir()
    settings = request.app.state.settings
    any_gemini_feature = any(
        (
            settings.agentic_discovery_enabled,
            settings.agentic_parsing_enabled,
            settings.ai_normalization_enabled,
        )
    )
    if not any_gemini_feature:
        gemini_agentic = "disabled"
    elif settings.gemini_api_key is None:
        gemini_agentic = "misconfigured"
    else:
        gemini_agentic = "ready"
    is_ready = database_ok and artifact_ok
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadyResponse(
        status="ready" if is_ready else "not_ready",
        database="ok" if database_ok else "error",
        artifact_store="ok" if artifact_ok else "error",
        gemini_agentic=gemini_agentic,
        agentic_discovery_enabled=settings.agentic_discovery_enabled,
        agentic_parsing_enabled=settings.agentic_parsing_enabled,
        ai_normalization_enabled=settings.ai_normalization_enabled,
    )
