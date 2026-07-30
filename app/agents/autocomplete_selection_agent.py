from dataclasses import dataclass

from app.agents.protocol import StructuredAgentClient, load_agent_prompt
from app.models.agentic import (
    AutocompleteSelectionDecision,
    AutocompleteSuggestion,
)

PROMPT_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class AutocompleteSelectionAgent:
    client: StructuredAgentClient
    prompt: str = load_agent_prompt("autocomplete_selection_v1.md")

    async def decide(
        self,
        *,
        imported_name: str,
        suggestions: tuple[AutocompleteSuggestion, ...],
    ) -> AutocompleteSelectionDecision:
        available_ids = {value.candidate_id for value in suggestions}
        decision = await self.client.generate_structured(
            agent_name="autocomplete_selection",
            prompt=self.prompt,
            payload={
                "prompt_version": PROMPT_VERSION,
                "imported_name": imported_name,
                "suggestions": [
                    value.model_dump(mode="json") for value in suggestions
                ],
            },
            response_model=AutocompleteSelectionDecision,
        )
        unknown = set(decision.selected_candidate_ids) - available_ids
        if unknown:
            raise ValueError(
                "Autocomplete agent selected an unknown candidate_id"
            )
        return decision
