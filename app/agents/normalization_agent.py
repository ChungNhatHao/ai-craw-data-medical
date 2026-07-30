from dataclasses import dataclass

from app.agents.disease_extraction_agent import _iter_evidence
from app.agents.protocol import (
    AgentContractError,
    StructuredAgentClient,
    load_agent_prompt,
    normalized_evidence,
    reject_raw_document,
)
from app.models.agentic import (
    DISEASE_FIELD_NAMES,
    AgentNormalizationInput,
    NormalizationResult,
)
from app.models.content import assert_safe_content_payload

PROMPT_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class NormalizationAgent:
    client: StructuredAgentClient
    prompt: str = load_agent_prompt("normalization_v1.md")

    async def normalize(
        self,
        normalization_input: AgentNormalizationInput,
    ) -> NormalizationResult:
        reject_raw_document(
            normalization_input.evidence_text,
            field_name="evidence_text",
        )
        payload: dict[str, object] = {
            "prompt_version": PROMPT_VERSION,
            **normalization_input.model_dump(mode="json"),
        }
        assert_safe_content_payload(payload)
        result = await self.client.generate_structured(
            agent_name="normalization",
            prompt=self.prompt,
            payload=payload,
            response_model=NormalizationResult,
        )
        allowed_changes = set(normalization_input.ambiguous_fields)
        if not set(result.changed_fields).issubset(allowed_changes):
            raise AgentContractError(
                "Normalization agent changed a non-ambiguous field"
            )
        actual_changes = {
            field_name
            for field_name in DISEASE_FIELD_NAMES
            if getattr(normalization_input.draft, field_name)
            != getattr(result.normalized_draft, field_name)
        }
        if actual_changes != set(result.changed_fields):
            raise AgentContractError(
                "Normalization changed_fields does not match the draft changes"
            )
        evidence_source = normalized_evidence(normalization_input.evidence_text)
        for evidence in _iter_evidence(result.normalized_draft):
            if (
                normalized_evidence(evidence.source_quote) not in evidence_source
                or normalized_evidence(evidence.value) not in evidence_source
            ):
                raise AgentContractError(
                    "Normalization agent returned a value or evidence absent from "
                    "clean content"
                )
        return result
