from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator

from app.models.tabs import DiseaseTabContent

SHA256_PATTERN = r"^[0-9a-f]{64}$"


class DiseaseSource(BaseModel):
    plugin: str = Field(min_length=1)
    url: HttpUrl
    canonical_url: HttpUrl
    retrieved_at: datetime
    content_hash: str = Field(pattern=SHA256_PATTERN)
    language: str = Field(min_length=2, max_length=16)


class DiseaseFields(BaseModel):
    name: str = Field(min_length=1)
    aliases: tuple[str, ...] = ()
    summary: str | None = None
    causes: tuple[str, ...] = ()
    risk_factors: tuple[str, ...] = ()
    symptoms: tuple[str, ...] = ()
    diagnosis: tuple[str, ...] = ()
    treatment: tuple[str, ...] = ()
    prevention: tuple[str, ...] = ()
    prognosis: str | None = None
    when_to_seek_care: tuple[str, ...] = ()


class DiseaseSection(BaseModel):
    heading: str = Field(min_length=1)
    level: int = Field(ge=1, le=6)
    order: int = Field(ge=1)
    markdown: str = Field(min_length=1)


class MenuHierarchyLevel(BaseModel):
    level: int = Field(ge=0)
    distance_from_disease: int = Field(ge=0)
    label: str = Field(min_length=1, max_length=1_000)
    url: HttpUrl | None = None
    is_current: bool = False


class ParseMetadata(BaseModel):
    method: Literal["rules", "llm", "rules+llm"]
    model: str | None = None
    prompt_version: str | None = None
    parser_version: str = Field(min_length=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    warnings: tuple[str, ...] = ()


class DiseaseDocument(BaseModel):
    schema_version: str = "1.3"
    document_id: str = Field(pattern=SHA256_PATTERN)
    source: DiseaseSource
    disease: DiseaseFields
    menu_hierarchy: tuple[MenuHierarchyLevel, ...] = ()
    sections: tuple[DiseaseSection, ...]
    tabs: tuple[DiseaseTabContent, ...] = ()
    parse_metadata: ParseMetadata

    @model_validator(mode="after")
    def validate_menu_hierarchy(self) -> "DiseaseDocument":
        if not self.menu_hierarchy:
            return self
        last = len(self.menu_hierarchy) - 1
        for index, node in enumerate(self.menu_hierarchy):
            if node.level != index:
                raise ValueError("Menu hierarchy levels must be contiguous")
            if node.distance_from_disease != last - index:
                raise ValueError(
                    "Menu hierarchy distance_from_disease is inconsistent"
                )
            if node.is_current != (index == last):
                raise ValueError(
                    "Only the final menu hierarchy node can be current"
                )
        return self


class PartialDiseaseFields(BaseModel):
    name: str | None = None
    aliases: tuple[str, ...] = ()
    summary: str | None = None
    causes: tuple[str, ...] = ()
    risk_factors: tuple[str, ...] = ()
    symptoms: tuple[str, ...] = ()
    diagnosis: tuple[str, ...] = ()
    treatment: tuple[str, ...] = ()
    prevention: tuple[str, ...] = ()
    prognosis: str | None = None
    when_to_seek_care: tuple[str, ...] = ()


class ParsingPolicy(BaseModel):
    timeout_seconds: float = Field(default=90, gt=0)
    max_attempts: int = Field(default=3, ge=1)
    retry_base_seconds: float = Field(default=2, ge=0)
    retry_max_seconds: float = Field(default=10, ge=0)
    max_model_calls: int = Field(default=40, ge=1)
    max_input_chars: int = Field(default=200_000, ge=1)


class ParsedArtifactResult(BaseModel):
    job_id: str
    item_id: str
    artifact_dir: str
    document: DiseaseDocument
    schema_hash: str = Field(pattern=SHA256_PATTERN)
    reused_artifacts: bool = False
