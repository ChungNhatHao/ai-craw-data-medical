import asyncio
from typing import TypeVar

import pytest
from pydantic import BaseModel, ValidationError

from app.agents.autocomplete_selection_agent import AutocompleteSelectionAgent
from app.agents.disease_detector import DiseaseDetector
from app.agents.disease_extraction_agent import DiseaseExtractionAgent
from app.agents.navigation_agent import NavigationAgent
from app.agents.normalization_agent import NormalizationAgent
from app.agents.protocol import AgentContractError
from app.models.agentic import (
    AgentNormalizationInput,
    AutocompleteSelectionDecision,
    AutocompleteSuggestion,
    CleanContent,
    DiseaseDecision,
    DiseaseDraft,
    EvidenceValue,
    NavigationDecision,
    NormalizationResult,
    ObservedLink,
    PageObservation,
)

T = TypeVar("T", bound=BaseModel)
CONTENT_HASH = "a" * 64


class FakeStructuredClient:
    def __init__(self, response: BaseModel) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    async def generate_structured(
        self,
        *,
        agent_name: str,
        prompt: str,
        payload: dict[str, object],
        response_model: type[T],
    ) -> T:
        self.calls.append(
            {
                "agent_name": agent_name,
                "prompt": prompt,
                "payload": payload,
            }
        )
        return response_model.model_validate(self.response.model_dump())


class SequencedStructuredClient:
    def __init__(self, responses: tuple[BaseModel, ...]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    async def generate_structured(
        self,
        *,
        agent_name: str,
        prompt: str,
        payload: dict[str, object],
        response_model: type[T],
    ) -> T:
        self.calls.append(
            {
                "agent_name": agent_name,
                "prompt": prompt,
                "payload": payload,
            }
        )
        return response_model.model_validate(
            self.responses.pop(0).model_dump()
        )


def observation(*, text: str = "Symptoms and treatment of Example disease.") -> PageObservation:
    return PageObservation(
        url="https://example.test/medical",
        canonical_url="https://example.test/medical",
        title="Example disease",
        headings=("Symptoms", "Treatment"),
        main_text_excerpt=text,
        medical_section_markers=("symptoms", "treatment"),
        links=(
            ObservedLink(
                candidate_id="candidate-1",
                label="Example disease",
                url="https://example.test/disease",
                rule_score=0.9,
            ),
        ),
        page_fingerprint="0123456789abcdef",
    )


def clean_content(*, markdown: str = "# Example disease\n\nSource symptom.") -> CleanContent:
    return CleanContent(
        source_url="https://example.test/disease",
        title="Example disease",
        headings=("Example disease",),
        clean_html="<article><h1>Example disease</h1></article>",
        markdown=markdown,
        plain_text="Example disease Source symptom.",
        removed_node_count=4,
        content_hash=CONTENT_HASH,
    )


def disease_draft() -> DiseaseDraft:
    return DiseaseDraft(
        name=EvidenceValue(
            value="Example disease",
            source_quote="Example disease",
            source_section="Title",
        ),
        symptoms=(
            EvidenceValue(
                value="Source symptom.",
                source_quote="Source symptom.",
                source_section="Symptoms",
            ),
        ),
    )


def test_navigation_agent_allows_only_observed_unvisited_candidate() -> None:
    accepted = FakeStructuredClient(
        NavigationDecision(
            action="open_candidate",
            candidate_id="candidate-1",
            confidence=0.95,
            reason_code="disease_candidate",
        )
    )
    decision = asyncio.run(
        NavigationAgent(accepted).decide(observation(), remaining_hops=2)
    )
    assert decision.candidate_id == "candidate-1"

    with pytest.raises(ValueError, match="unknown or visited"):
        asyncio.run(
            NavigationAgent(accepted).decide(
                observation(),
                visited_candidate_ids=frozenset({"candidate-1"}),
                remaining_hops=2,
            )
        )


def test_autocomplete_agent_selects_only_supplied_suggestion_and_explains() -> None:
    suggestions = (
        AutocompleteSuggestion(
            candidate_id="autocomplete-1",
            label="Cardiac arrhythmias",
        ),
        AutocompleteSuggestion(
            candidate_id="autocomplete-2",
            label=(
                "Functional cardiac arrhythmias - "
                "Functional cardiovascular symptoms"
            ),
        ),
    )
    accepted = FakeStructuredClient(
        AutocompleteSelectionDecision(
            selected_candidate_ids=("autocomplete-1",),
            confidence=0.97,
            reason_code="singular_plural",
            reason=(
                "Cardiac arrhythmias chỉ khác tên import ở dạng số nhiều."
            ),
        )
    )

    decision = asyncio.run(
        AutocompleteSelectionAgent(accepted).decide(
            imported_name="Cardiac arrhythmia",
            suggestions=suggestions,
        )
    )

    assert decision.selected_candidate_ids == ("autocomplete-1",)
    assert decision.reason
    assert accepted.calls[0]["agent_name"] == "autocomplete_selection"

    invalid = FakeStructuredClient(
        AutocompleteSelectionDecision(
            selected_candidate_ids=("invented",),
            confidence=0.9,
            reason_code="medical_semantic_match",
            reason="Invented result",
        )
    )
    with pytest.raises(ValueError, match="unknown candidate_id"):
        asyncio.run(
            AutocompleteSelectionAgent(invalid).decide(
                imported_name="Cardiac arrhythmia",
                suggestions=suggestions,
            )
        )


def test_autocomplete_agent_keeps_all_plausible_ambiguous_suggestions() -> None:
    suggestions = (
        AutocompleteSuggestion(
            candidate_id="autocomplete-1",
            label="Type 1 example disease",
        ),
        AutocompleteSuggestion(
            candidate_id="autocomplete-2",
            label="Type 2 example disease",
        ),
    )
    client = FakeStructuredClient(
        AutocompleteSelectionDecision(
            selected_candidate_ids=("autocomplete-1", "autocomplete-2"),
            confidence=0.72,
            reason_code="ambiguous",
            reason="Cả hai gợi ý đều là biến thể bệnh hợp lý.",
        )
    )

    decision = asyncio.run(
        AutocompleteSelectionAgent(client).decide(
            imported_name="Example disease",
            suggestions=suggestions,
        )
    )

    assert decision.selected_candidate_ids == (
        "autocomplete-1",
        "autocomplete-2",
    )


def test_disease_detector_rejects_raw_html_and_ungrounded_evidence() -> None:
    positive = FakeStructuredClient(
        DiseaseDecision(
            is_disease_detail=True,
            confidence=0.95,
            disease_name="Example disease",
            evidence=("not in the page",),
            reason_code="confirmed_detail",
        )
    )
    with pytest.raises(ValueError, match="ungrounded"):
        asyncio.run(DiseaseDetector(positive).detect(observation()))

    with pytest.raises(AgentContractError, match="BeautifulSoup"):
        asyncio.run(
            DiseaseDetector(positive).detect(
                observation(text="<html><body>Example disease</body></html>")
            )
        )


def test_extraction_agent_never_sends_clean_html_and_checks_grounding() -> None:
    client = FakeStructuredClient(disease_draft())
    result = asyncio.run(DiseaseExtractionAgent(client).extract(clean_content()))

    assert result.name.value == "Example disease"
    payload = client.calls[0]["payload"]
    assert isinstance(payload, dict)
    assert "clean_html" not in payload
    assert "raw_html" not in payload

    hallucinated = disease_draft().model_copy(
        update={
            "symptoms": (
                EvidenceValue(
                    value="Invented symptom",
                    source_quote="Invented symptom",
                ),
            )
        }
    )
    failed_client = FakeStructuredClient(hallucinated)
    with pytest.raises(AgentContractError, match="absent"):
        asyncio.run(
            DiseaseExtractionAgent(failed_client).extract(
                clean_content()
            )
        )
    assert len(failed_client.calls) == 2
    assert "grounding_retry" in failed_client.calls[1]["payload"]

    paraphrased = disease_draft().model_copy(
        update={
            "symptoms": (
                EvidenceValue(
                    value="A paraphrased symptom",
                    source_quote="Source symptom.",
                ),
            )
        }
    )
    repaired = asyncio.run(
        DiseaseExtractionAgent(FakeStructuredClient(paraphrased)).extract(
            clean_content()
        )
    )
    assert repaired.symptoms[0].value == "Source symptom."


def test_extraction_agent_repairs_first_ungrounded_draft_on_retry() -> None:
    ungrounded = disease_draft().model_copy(
        update={
            "symptoms": (
                EvidenceValue(
                    value="Invented symptom",
                    source_quote="Invented symptom",
                ),
            )
        }
    )
    client = SequencedStructuredClient((ungrounded, disease_draft()))

    repaired = asyncio.run(
        DiseaseExtractionAgent(client).extract(clean_content())
    )

    assert repaired == disease_draft()
    assert len(client.calls) == 2
    retry = client.calls[1]
    assert "GROUNDING REPAIR RETRY" in str(retry["prompt"])
    assert retry["payload"]["grounding_retry"] == {
        "attempt": 2,
        "reason": "source_quote_not_verbatim",
    }


def test_content_contract_forbids_raw_html_field() -> None:
    payload = {
        **clean_content().model_dump(mode="json"),
        "raw_html": "<html>secret</html>",
    }
    with pytest.raises(ValidationError, match="raw_html"):
        CleanContent.model_validate(payload)


def test_normalization_changes_only_ambiguous_grounded_fields() -> None:
    source = AgentNormalizationInput(
        source_url="https://example.test/disease",
        content_hash=CONTENT_HASH,
        draft=disease_draft(),
        ambiguous_fields=("symptoms",),
        evidence_text="Example disease Source symptom.",
    )
    normalized_draft = disease_draft().model_copy(
        update={
            "symptoms": (
                EvidenceValue(
                    value="source symptom.",
                    source_quote="Source symptom.",
                    source_section="Symptoms",
                ),
            )
        }
    )
    valid_result = NormalizationResult(
        normalized_draft=normalized_draft,
        changed_fields=("symptoms",),
    )
    result = asyncio.run(
        NormalizationAgent(FakeStructuredClient(valid_result)).normalize(source)
    )
    assert result.changed_fields == ("symptoms",)

    invalid_result = valid_result.model_copy(update={"changed_fields": ("treatment",)})
    with pytest.raises(AgentContractError, match="non-ambiguous"):
        asyncio.run(
            NormalizationAgent(FakeStructuredClient(invalid_result)).normalize(
                source
            )
        )

    unsafe_source = source.model_copy(
        update={"evidence_text": "<script>alert(1)</script>"}
    )
    with pytest.raises(AgentContractError, match="BeautifulSoup"):
        asyncio.run(
            NormalizationAgent(FakeStructuredClient(valid_result)).normalize(
                unsafe_source
            )
        )
