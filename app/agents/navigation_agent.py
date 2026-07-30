from dataclasses import dataclass

from app.agents.protocol import StructuredAgentClient, load_agent_prompt
from app.models.agentic import NavigationDecision, PageObservation

PROMPT_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class NavigationAgent:
    client: StructuredAgentClient
    prompt: str = load_agent_prompt("navigation_v1.md")

    async def decide(
        self,
        observation: PageObservation,
        *,
        visited_candidate_ids: frozenset[str] = frozenset(),
        remaining_hops: int,
    ) -> NavigationDecision:
        available_ids = {
            link.candidate_id
            for link in observation.links
            if link.candidate_id not in visited_candidate_ids
        }
        decision = await self.client.generate_structured(
            agent_name="navigation",
            prompt=self.prompt,
            payload={
                "prompt_version": PROMPT_VERSION,
                "observation": observation.model_dump(mode="json"),
                "visited_candidate_ids": sorted(visited_candidate_ids),
                "remaining_hops": max(remaining_hops, 0),
            },
            response_model=NavigationDecision,
        )
        if decision.action == "open_candidate":
            if decision.candidate_id not in available_ids:
                raise ValueError(
                    "Navigation agent selected an unknown or visited candidate_id"
                )
            if remaining_hops <= 0:
                raise ValueError("Navigation agent cannot open a candidate at hop limit")
        return decision
