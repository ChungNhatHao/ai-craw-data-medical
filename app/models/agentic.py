from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

SHA256_PATTERN = r"^[0-9a-f]{64}$"

DiseaseFieldName = Literal[
    "name",
    "aliases",
    "summary",
    "causes",
    "risk_factors",
    "symptoms",
    "diagnosis",
    "treatment",
    "prevention",
    "prognosis",
    "when_to_seek_care",
]
DISEASE_FIELD_NAMES: tuple[DiseaseFieldName, ...] = (
    "name",
    "aliases",
    "summary",
    "causes",
    "risk_factors",
    "symptoms",
    "diagnosis",
    "treatment",
    "prevention",
    "prognosis",
    "when_to_seek_care",
)


class AgenticModel(BaseModel):
    """Strict immutable contract used at every model boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ObservedLink(AgenticModel):
    candidate_id: str = Field(min_length=1, max_length=128)
    label: str | None = Field(default=None, max_length=500)
    url: HttpUrl
    dom_region: str | None = Field(default=None, max_length=100)
    rule_score: float = Field(default=0, ge=0, le=1)


class PageObservation(AgenticModel):
    url: HttpUrl
    canonical_url: HttpUrl
    title: str | None = Field(default=None, max_length=1_000)
    breadcrumb: tuple[str, ...] = ()
    headings: tuple[str, ...] = ()
    main_text_excerpt: str = Field(default="", max_length=30_000)
    medical_section_markers: tuple[str, ...] = ()
    links: tuple[ObservedLink, ...] = Field(default=(), max_length=80)
    page_fingerprint: str = Field(min_length=12, max_length=128)

    @model_validator(mode="after")
    def candidate_ids_are_unique(self) -> "PageObservation":
        candidate_ids = [link.candidate_id for link in self.links]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("Page observation candidate IDs must be unique")
        return self


NavigationAction = Literal[
    "open_candidate",
    "go_back",
    "stop",
    "needs_operator",
]
NavigationReason = Literal[
    "medical_category",
    "disease_candidate",
    "pagination",
    "no_candidate",
    "blocked",
]


class NavigationDecision(AgenticModel):
    action: NavigationAction
    candidate_id: str | None = None
    confidence: float = Field(ge=0, le=1)
    reason_code: NavigationReason

    @model_validator(mode="after")
    def candidate_matches_action(self) -> "NavigationDecision":
        if self.action == "open_candidate" and self.candidate_id is None:
            raise ValueError("open_candidate requires candidate_id")
        if self.action != "open_candidate" and self.candidate_id is not None:
            raise ValueError("candidate_id is only valid for open_candidate")
        return self


AutocompleteSelectionReason = Literal[
    "exact_name",
    "singular_plural",
    "medical_semantic_match",
    "ambiguous",
    "no_suitable_suggestion",
]


class AutocompleteSuggestion(AgenticModel):
    candidate_id: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=1_000)


class AutocompleteSelectionDecision(AgenticModel):
    selected_candidate_ids: tuple[str, ...] = Field(default=(), max_length=10)
    confidence: float = Field(ge=0, le=1)
    reason_code: AutocompleteSelectionReason
    reason: str = Field(min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def selection_matches_reason(self) -> "AutocompleteSelectionDecision":
        values = self.selected_candidate_ids
        if len(values) != len(set(values)):
            raise ValueError("Autocomplete candidate IDs must be unique")
        if self.reason_code == "no_suitable_suggestion" and values:
            raise ValueError("No-suggestion decision cannot select a candidate")
        if self.reason_code == "ambiguous" and len(values) < 2:
            raise ValueError("Ambiguous decision requires multiple candidates")
        if self.reason_code not in {"ambiguous", "no_suitable_suggestion"}:
            if len(values) != 1:
                raise ValueError(
                    "Certain autocomplete decision requires one candidate"
                )
        return self


DiseaseReason = Literal[
    "confirmed_detail",
    "listing_page",
    "menu_page",
    "login_page",
    "blocked_page",
    "insufficient_content",
]


class DiseaseDecision(AgenticModel):
    is_disease_detail: bool
    confidence: float = Field(ge=0, le=1)
    disease_name: str | None = Field(default=None, max_length=1_000)
    evidence: tuple[str, ...] = ()
    negative_signals: tuple[str, ...] = ()
    reason_code: DiseaseReason

    @model_validator(mode="after")
    def confirmed_disease_has_grounding(self) -> "DiseaseDecision":
        if self.is_disease_detail:
            if not self.disease_name or not self.disease_name.strip():
                raise ValueError("Confirmed disease page requires disease_name")
            if not self.evidence:
                raise ValueError("Confirmed disease page requires evidence")
            if any(not quote.strip() for quote in self.evidence):
                raise ValueError("Confirmed disease evidence cannot be blank")
            if self.reason_code != "confirmed_detail":
                raise ValueError("Confirmed disease page requires confirmed_detail")
        elif self.reason_code == "confirmed_detail":
            raise ValueError("confirmed_detail requires is_disease_detail=true")
        return self


class EvidenceValue(AgenticModel):
    value: str = Field(min_length=1)
    source_quote: str = Field(min_length=1)
    source_section: str | None = Field(default=None, max_length=1_000)


class DiseaseDraft(AgenticModel):
    name: EvidenceValue
    aliases: tuple[EvidenceValue, ...] = ()
    summary: EvidenceValue | None = None
    causes: tuple[EvidenceValue, ...] = ()
    risk_factors: tuple[EvidenceValue, ...] = ()
    symptoms: tuple[EvidenceValue, ...] = ()
    diagnosis: tuple[EvidenceValue, ...] = ()
    treatment: tuple[EvidenceValue, ...] = ()
    prevention: tuple[EvidenceValue, ...] = ()
    prognosis: EvidenceValue | None = None
    when_to_seek_care: tuple[EvidenceValue, ...] = ()


class CleanContent(AgenticModel):
    """Output of the deterministic BeautifulSoup boundary."""

    source_url: HttpUrl
    title: str | None = Field(default=None, max_length=1_000)
    headings: tuple[str, ...] = ()
    clean_html: str
    markdown: str
    plain_text: str
    removed_node_count: int = Field(ge=0)
    content_hash: str = Field(pattern=SHA256_PATTERN)


class AgentNormalizationInput(AgenticModel):
    """AI-safe normalization payload; raw HTML is deliberately not a field."""

    source_url: HttpUrl
    content_hash: str = Field(pattern=SHA256_PATTERN)
    draft: DiseaseDraft
    ambiguous_fields: tuple[DiseaseFieldName, ...] = ()
    evidence_text: str = Field(min_length=1, max_length=200_000)


class NormalizationResult(AgenticModel):
    normalized_draft: DiseaseDraft
    changed_fields: tuple[DiseaseFieldName, ...] = ()
    ambiguous_fields: tuple[DiseaseFieldName, ...] = ()
    warnings: tuple[str, ...] = ()
