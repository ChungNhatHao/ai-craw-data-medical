from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.state import CrawlState
from app.plugins.base import SitePlugin
from app.repositories.jobs import JobRepository


def build_demo_graph(
    plugin: SitePlugin,
    jobs: JobRepository,
) -> CompiledStateGraph[CrawlState, None, CrawlState, CrawlState]:
    """Build the Day-1 graph used to verify orchestration boundaries."""

    async def start_job(state: CrawlState) -> CrawlState:
        await jobs.update_status(state["job_id"], "running")
        return {**state, "status": "running"}

    async def discover(state: CrawlState) -> CrawlState:
        items = await plugin.discover_demo_items()
        return {**state, "discovered_count": len(items)}

    async def finish_job(state: CrawlState) -> CrawlState:
        await jobs.update_status(state["job_id"], "completed")
        return {**state, "status": "completed"}

    graph = StateGraph(CrawlState)
    graph.add_node("start_job", start_job)
    graph.add_node("discover", discover)
    graph.add_node("finish_job", finish_job)
    graph.add_edge(START, "start_job")
    graph.add_edge("start_job", "discover")
    graph.add_edge("discover", "finish_job")
    graph.add_edge("finish_job", END)
    return graph.compile()
