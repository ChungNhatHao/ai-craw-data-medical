from dataclasses import dataclass

from app.agents.protocol import (
    AgentContractError,
    StructuredAgentClient,
    load_agent_prompt,
    normalized_evidence,
    reject_raw_document,
)
from app.models.agentic import CleanContent, DiseaseDraft, EvidenceValue
from app.models.content import assert_safe_content_payload

PROMPT_VERSION = "1.2.0"
GROUNDING_RETRY_INSTRUCTION = """
GROUNDING REPAIR RETRY:
The previous structured draft was rejected because at least one source_quote
was not a verbatim substring of the supplied cleaned content. Rebuild the
entire response. Every source_quote must be copied exactly from title,
markdown, or plain_text, including punctuation and spelling. Omit a field when
no exact supporting quote exists. Never paraphrase source_quote.
""".strip()


@dataclass(frozen=True, slots=True)
class DiseaseExtractionAgent:
    client: StructuredAgentClient
    prompt: str = load_agent_prompt("disease_extraction_v1.md")

    async def extract(self, content: CleanContent) -> DiseaseDraft:
        reject_raw_document(content.markdown, field_name="markdown")
        reject_raw_document(content.plain_text, field_name="plain_text")
        payload: dict[str, object] = {
            "prompt_version": PROMPT_VERSION,
            "source_url": str(content.source_url),
            "title": content.title,
            "headings": list(content.headings),
            "markdown": content.markdown,
            "plain_text": content.plain_text,
            "content_hash": content.content_hash,
        }
        assert_safe_content_payload(payload)
        draft = await self.client.generate_structured(
            agent_name="disease_extraction",
            prompt=self.prompt,
            payload=payload,
            response_model=DiseaseDraft,
        )
        evidence_source = normalized_evidence(
            "\n".join((content.title or "", content.markdown, content.plain_text))
        )
        try:
            return _ground_draft(draft, evidence_source)
        except AgentContractError:
            retry_payload = {
                **payload,
                "grounding_retry": {
                    "attempt": 2,
                    "reason": "source_quote_not_verbatim",
                },
            }
            repaired = await self.client.generate_structured(
                agent_name="disease_extraction",
                prompt=f"{self.prompt}\n\n{GROUNDING_RETRY_INSTRUCTION}",
                payload=retry_payload,
                response_model=DiseaseDraft,
            )
            return _ground_draft(repaired, evidence_source)


def _ground_draft(
    draft: DiseaseDraft,
    evidence_source: str,
) -> DiseaseDraft:
    def ground(value: EvidenceValue) -> EvidenceValue:
        if normalized_evidence(value.source_quote) not in evidence_source:
            raise AgentContractError(
                "Disease extraction returned a source_quote absent from "
                "BeautifulSoup-cleaned content"
            )
        if normalized_evidence(value.value) in evidence_source:
            return value
        # A model may shorten or lightly paraphrase `value` despite the
        # contract. Falling back to its verified verbatim quote is a safe,
        # deterministic repair: no ungrounded text reaches the final JSON.
        return value.model_copy(update={"value": value.source_quote})

    updates: dict[str, object] = {"name": ground(draft.name)}
    for field_name in ("summary", "prognosis"):
        value = getattr(draft, field_name)
        updates[field_name] = ground(value) if value is not None else None
    for field_name in (
        "aliases",
        "causes",
        "risk_factors",
        "symptoms",
        "diagnosis",
        "treatment",
        "prevention",
        "when_to_seek_care",
    ):
        updates[field_name] = tuple(
            ground(value) for value in getattr(draft, field_name)
        )
    return draft.model_copy(update=updates)


def _iter_evidence(draft: DiseaseDraft) -> tuple[EvidenceValue, ...]:
    scalar_values = tuple(
        value
        for value in (draft.name, draft.summary, draft.prognosis)
        if value is not None
    )
    list_values = (
        *draft.aliases,
        *draft.causes,
        *draft.risk_factors,
        *draft.symptoms,
        *draft.diagnosis,
        *draft.treatment,
        *draft.prevention,
        *draft.when_to_seek_care,
    )
    return (*scalar_values, *list_values)
