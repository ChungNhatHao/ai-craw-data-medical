import asyncio

from httpx import ASGITransport, AsyncClient

from app.api.application import create_app
from app.core.config import Settings
from app.models.run import (
    RunRequest,
    RunSnapshot,
    RunStage,
    RunStageName,
    RunStartResponse,
    RunState,
)
from app.services.xlsx_import import build_disease_import_template

JOB_ID = "11111111-1111-1111-1111-111111111111"


class FakeRunManager:
    async def start(self, request: RunRequest) -> RunStartResponse:
        assert request.password.get_secret_value() == "test-secret"
        if request.discovery_mode == "import":
            assert request.disease_names == ("Sepsis", "Down syndrome")
            assert request.max_items == 2
            assert request.expand_disease_categories is True
            assert request.category_max_depth == 5
            assert request.category_max_nodes == 100
            assert request.category_max_diseases == 100
        return RunStartResponse(job_id=JOB_ID, state=RunState.QUEUED)

    async def get(self, job_id: str) -> RunSnapshot | None:
        if job_id != JOB_ID:
            return None
        return RunSnapshot(
            job_id=job_id,
            state=RunState.RUNNING,
            stages=(
                RunStage(
                    name=RunStageName.AUTHENTICATE,
                    label="Đăng nhập & session",
                ),
            ),
        )

    async def close(self) -> None:
        return None


def test_operator_ui_and_progress_api(settings: Settings) -> None:
    async def scenario() -> None:
        app = create_app(settings)
        transport = ASGITransport(app=app)
        async with app.router.lifespan_context(app):
            app.state.run_manager = FakeRunManager()
            async with AsyncClient(
                transport=transport,
                base_url="http://test",
            ) as client:
                page = await client.get("/")
                styles = await client.get("/static/styles.css")
                script = await client.get("/static/app.js")
                started = await client.post(
                    "/api/v1/jobs/runs/start",
                    json={
                        "url": (
                            "https://www.genre-manuals.com/"
                            "sites/CLUE/home.html"
                        ),
                        "username": "test-user",
                        "password": "test-secret",
                        "max_items": 2,
                        "authorization_confirmed": True,
                    },
                )
                imported = await client.post(
                    "/api/v1/jobs/runs/start",
                    json={
                        "url": (
                            "https://www.genre-manuals.com/"
                            "sites/CLUE/home.html"
                        ),
                        "username": "test-user",
                        "password": "test-secret",
                        "max_items": 1,
                        "discovery_mode": "import",
                        "disease_names": [
                            " Sepsis ",
                            "Down syndrome",
                            "sepsis",
                        ],
                        "expand_disease_categories": True,
                        "category_max_depth": 5,
                        "category_max_nodes": 100,
                        "category_max_diseases": 100,
                        "authorization_confirmed": True,
                    },
                )
                template = await client.get(
                    "/api/v1/jobs/imports/xlsx/template"
                )
                preview = await client.post(
                    "/api/v1/jobs/imports/xlsx/parse",
                    content=build_disease_import_template(),
                    headers={
                        "Content-Type": (
                            "application/vnd.openxmlformats-officedocument."
                            "spreadsheetml.sheet"
                        )
                    },
                )
                progress = await client.get(
                    f"/api/v1/jobs/runs/{JOB_ID}"
                )

        assert page.status_code == 200
        assert 'id="runForm"' in page.text
        assert 'type="password"' in page.text
        assert 'id="diseaseViewer"' in page.text
        assert 'id="agenticDiscovery"' in page.text
        assert 'id="agenticParsing"' in page.text
        assert 'id="aiNormalization"' in page.text
        assert 'id="automaticModeTab"' in page.text
        assert 'id="importModeTab"' in page.text
        assert 'id="diseaseNamesFile"' in page.text
        assert "Tải XLSX mẫu" in page.text
        assert 'id="importAuditLink"' in page.text
        assert 'id="expandDiseaseCategories"' in page.text
        assert 'id="categoryMaxDepth"' in page.text
        assert 'id="categoryMaxNodes"' in page.text
        assert 'id="categoryMaxDiseases"' in page.text
        assert 'id="categoryExpansionLink"' in page.text
        assert 'id="siteProfileLink"' in page.text
        assert 'id="coverageReportLink"' in page.text
        assert 'id="coverageStatus"' in page.text
        assert 'id="searchDecisionPanel"' in page.text
        assert "Quyết định chọn tên bệnh" in page.text
        assert "Nhật ký menu cha-con" in page.text
        assert "test-secret" not in page.text
        assert styles.status_code == 200
        assert "--teal" in styles.text
        assert script.status_code == 200
        assert "activeCrawlerJob" in script.text
        assert "renderDisease" in script.text
        assert "Cha trực tiếp" in script.text
        assert "Đường dẫn đầy đủ" in script.text
        assert "parent_classification" in script.text
        assert "agentic_discovery" in script.text
        assert "agentic_parsing" in script.text
        assert "ai_normalization" in script.text
        assert "discovery_mode" in script.text
        assert "disease_names" in script.text
        assert "expand_disease_categories" in script.text
        assert "category_max_depth" in script.text
        assert "category_max_nodes" in script.text
        assert "category_max_diseases" in script.text
        assert "category-expansion.json" in script.text
        assert "site-profile.json" in script.text
        assert "coverage-report.json" in script.text
        assert "normalizeProvenance" in script.text
        assert "renderSearchDecisions" in script.text
        assert "autocomplete_selected_name" in script.text
        assert started.status_code == 202
        assert started.json() == {"job_id": JOB_ID, "state": "queued"}
        assert "password" not in started.text
        assert imported.status_code == 202
        assert "password" not in imported.text
        assert template.status_code == 200
        assert template.content.startswith(b"PK")
        assert "disease-import-template.xlsx" in (
            template.headers["content-disposition"]
        )
        assert preview.status_code == 200
        assert preview.json() == {
            "disease_names": ["Down syndrome", "Sepsis"],
            "count": 2,
        }
        assert progress.status_code == 200
        assert progress.json()["state"] == "running"

    asyncio.run(scenario())
