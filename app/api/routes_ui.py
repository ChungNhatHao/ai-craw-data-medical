from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, Response

router = APIRouter(tags=["ui"])
WEB_ROOT = Path(__file__).parents[1] / "web"
INDEX_HTML = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
STYLES = (WEB_ROOT / "styles.css").read_text(encoding="utf-8")
SCRIPT = (WEB_ROOT / "app.js").read_text(encoding="utf-8")


@router.get("/", include_in_schema=False)
async def operator_console() -> HTMLResponse:
    return HTMLResponse(INDEX_HTML)


@router.get("/static/styles.css", include_in_schema=False)
async def operator_styles() -> Response:
    return Response(STYLES, media_type="text/css")


@router.get("/static/app.js", include_in_schema=False)
async def operator_script() -> Response:
    return Response(SCRIPT, media_type="text/javascript")
