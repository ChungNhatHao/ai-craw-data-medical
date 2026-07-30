from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from playwright.async_api import Page

from app.agents.state import RawFetchState
from app.models.discovery import DiscoveredItem
from app.services.detail_fetch import DetailFetchService


def build_raw_fetch_graph(
    *,
    page: Page,
    item: DiscoveredItem,
    service: DetailFetchService,
) -> CompiledStateGraph[RawFetchState, None, RawFetchState, RawFetchState]:
    """Build the Day-5 item subgraph through the persist_raw checkpoint."""

    async def prepare_item(state: RawFetchState) -> RawFetchState:
        return {**state, "stage": "fetching"}

    async def fetch_and_persist_raw(state: RawFetchState) -> RawFetchState:
        result = await service.run(page, job_id=state["job_id"], item=item)
        return {
            **state,
            "stage": "fetched",
            "artifact_dir": result.artifact_dir,
            "attempt_count": result.attempt_count,
            "reused_artifacts": result.reused_artifacts,
        }

    graph = StateGraph(RawFetchState)
    graph.add_node("prepare_item", prepare_item)
    graph.add_node("persist_raw", fetch_and_persist_raw)
    graph.add_edge(START, "prepare_item")
    graph.add_edge("prepare_item", "persist_raw")
    graph.add_edge("persist_raw", END)
    return graph.compile()
