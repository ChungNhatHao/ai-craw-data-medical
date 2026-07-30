from dataclasses import dataclass

from app.agents.protocol import (
    StructuredAgentClient,
    load_agent_prompt,
    normalized_evidence,
    reject_raw_document,
)
from app.models.agentic import DiseaseDecision, PageObservation
from app.models.content import assert_safe_content_payload

PROMPT_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class DiseaseDetector:
    client: StructuredAgentClient
    prompt: str = load_agent_prompt("disease_detector_v1.md")

    async def detect(self, observation: PageObservation) -> DiseaseDecision:
        reject_raw_document(
            observation.main_text_excerpt,
            field_name="main_text_excerpt",
        )
        payload: dict[str, object] = {
            "prompt_version": PROMPT_VERSION,
            "observation": observation.model_dump(
                mode="json",
                exclude={"links"},
            ),
        }
        assert_safe_content_payload(payload)
        decision = await self.client.generate_structured(
            agent_name="disease_detector",
            prompt=self.prompt,
            payload=payload,
            response_model=DiseaseDecision,
        )
        if decision.is_disease_detail:
            evidence_source = normalized_evidence(
                "\n".join(
                    (
                        observation.title or "",
                        *observation.headings,
                        observation.main_text_excerpt,
                    )
                )
            )
            if any(
                normalized_evidence(quote) not in evidence_source
                for quote in decision.evidence
            ):
                raise ValueError("Disease detector returned ungrounded evidence")
        return decision
