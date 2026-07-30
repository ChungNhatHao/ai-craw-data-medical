import asyncio

from httpx import ASGITransport, AsyncClient

from app.api.application import create_app
from app.core.config import Settings


def test_health_endpoints(settings: Settings) -> None:
    async def scenario() -> None:
        app = create_app(settings)
        transport = ASGITransport(app=app)
        async with app.router.lifespan_context(app):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                live_response = await client.get("/api/v1/health/live")
                ready_response = await client.get("/api/v1/health/ready")

        assert live_response.status_code == 200
        assert live_response.json() == {"status": "ok"}
        assert ready_response.status_code == 200
        assert ready_response.json() == {
            "status": "ready",
            "database": "ok",
            "artifact_store": "ok",
            "gemini_agentic": "disabled",
        }

    asyncio.run(scenario())
