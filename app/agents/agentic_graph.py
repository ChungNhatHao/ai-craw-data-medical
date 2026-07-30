from typing import Literal, NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from playwright.async_api import Page

from app.agents.disease_detector import DiseaseDetector
from app.agents.navigation_agent import NavigationAgent
from app.models.agentic import (
    DiseaseDecision,
    NavigationDecision,
    PageObservation,
)
from app.models.navigation import PageType
from app.plugins.genre_manuals.plugin import GenreManualsPlugin
from app.services.page_observer import PageObserver


class AgenticStepState(TypedDict):
    visited_urls: tuple[str, ...]
    visited_candidate_ids: tuple[str, ...]
    remaining_hops: int
    observation: NotRequired[PageObservation]
    page_type: NotRequired[PageType]
    disease_decision: NotRequired[DiseaseDecision]
    navigation_decision: NotRequired[NavigationDecision]
    accepted: NotRequired[bool]


def build_agentic_step_graph(
    *,
    page: Page,
    plugin: GenreManualsPlugin,
    observer: PageObserver,
    disease_detector: DiseaseDetector,
    navigation_agent: NavigationAgent,
    disease_confidence_threshold: float,
) -> CompiledStateGraph[
    AgenticStepState,
    None,
    AgenticStepState,
    AgenticStepState,
]:
    """Compile one observe/classify/detect/decide step of the browser loop."""

    async def observe(state: AgenticStepState) -> AgenticStepState:
        observation = await observer.observe(
            page,
            visited_urls=frozenset(state["visited_urls"]),
        )
        return {**state, "observation": observation}

    async def classify(state: AgenticStepState) -> AgenticStepState:
        return {
            **state,
            "page_type": (await plugin.classify_page(page)).page_type,
        }

    async def detect(state: AgenticStepState) -> AgenticStepState:
        decision = await disease_detector.detect(state["observation"])
        accepted = (
            state["page_type"] is PageType.DISEASE_DETAIL
            and decision.is_disease_detail
            and decision.confidence >= disease_confidence_threshold
        )
        return {
            **state,
            "disease_decision": decision,
            "accepted": accepted,
        }

    async def route_after_classify(
        state: AgenticStepState,
    ) -> Literal["detect", "terminal"]:
        return (
            "terminal"
            if state["page_type"]
            in {PageType.LOGIN, PageType.BLOCKED_OR_CAPTCHA}
            else "detect"
        )

    async def route_after_detect(
        state: AgenticStepState,
    ) -> Literal["navigate", "accepted"]:
        return "accepted" if state["accepted"] else "navigate"

    async def navigate(state: AgenticStepState) -> AgenticStepState:
        decision = await navigation_agent.decide(
            state["observation"],
            visited_candidate_ids=frozenset(state["visited_candidate_ids"]),
            remaining_hops=state["remaining_hops"],
        )
        return {**state, "navigation_decision": decision}

    graph = StateGraph(AgenticStepState)
    graph.add_node("observe", observe)
    graph.add_node("classify", classify)
    graph.add_node("detect", detect)
    graph.add_node("navigate", navigate)
    graph.add_edge(START, "observe")
    graph.add_edge("observe", "classify")
    graph.add_conditional_edges(
        "classify",
        route_after_classify,
        {"detect": "detect", "terminal": END},
    )
    graph.add_conditional_edges(
        "detect",
        route_after_detect,
        {"navigate": "navigate", "accepted": END},
    )
    graph.add_edge("navigate", END)
    return graph.compile()
