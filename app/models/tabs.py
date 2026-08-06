from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator

TabKey = Literal["info", "life_dd_tpd", "ip", "health"]


class RawTabRelatedDetail(BaseModel):
    label: str = Field(min_length=1)
    url: HttpUrl
    html: str = ""
    available: bool = True
    warning: str | None = None


class RawDiseaseTab(BaseModel):
    key: TabKey
    label: str = Field(min_length=1)
    source_url: HttpUrl
    html: str = ""
    available: bool = True
    warning: str | None = None
    related_details: tuple[RawTabRelatedDetail, ...] = ()


class DiseaseTabTable(BaseModel):
    rows: tuple[tuple[str, ...], ...] = ()


class TabRelatedDetail(BaseModel):
    label: str = Field(min_length=1)
    url: HttpUrl
    available: bool = True
    plain_text: str = ""
    markdown: str = ""
    content_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    warnings: tuple[str, ...] = ()


class ClassificationRow(BaseModel):
    classification_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    parent_classification_id: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    parent_classification: str | None = None
    classification: str = Field(min_length=1)
    level: int = Field(ge=0)
    classification_path: tuple[str, ...] = Field(min_length=1)
    is_group: bool
    ratings: dict[str, str] = Field(default_factory=dict)
    code: str | None = None
    raw_cells: tuple[str, ...] = ()
    related_details: tuple[TabRelatedDetail, ...] = ()

    @model_validator(mode="after")
    def path_matches_level(self) -> "ClassificationRow":
        if self.level != len(self.classification_path) - 1:
            raise ValueError(
                "Classification level must match path depth"
            )
        if self.classification != self.classification_path[-1]:
            raise ValueError(
                "Classification must be the final path segment"
            )
        expected_parent = (
            self.classification_path[-2] if self.level > 0 else None
        )
        if self.parent_classification != expected_parent:
            raise ValueError(
                "Classification parent must match the preceding path segment"
            )
        if (self.parent_classification_id is None) != (self.level == 0):
            raise ValueError(
                "Only root classifications can omit the parent ID"
            )
        return self


class ClassificationNode(BaseModel):
    classification_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    parent_classification_id: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    parent_classification: str | None = None
    classification: str = Field(min_length=1)
    level: int = Field(ge=0)
    classification_path: tuple[str, ...] = Field(min_length=1)
    is_group: bool
    ratings: dict[str, str] = Field(default_factory=dict)
    code: str | None = None
    children: tuple["ClassificationNode", ...] = ()


class DiseaseClassificationTable(BaseModel):
    headers: tuple[str, ...] = ()
    rows: tuple[ClassificationRow, ...] = ()
    tree: tuple[ClassificationNode, ...] = ()
    warnings: tuple[str, ...] = ()


class DiseaseTabContent(BaseModel):
    key: TabKey
    label: str = Field(min_length=1)
    source_url: HttpUrl
    available: bool = True
    plain_text: str = ""
    markdown: str = ""
    tables: tuple[DiseaseTabTable, ...] = ()
    classification_table: DiseaseClassificationTable | None = None
    content_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    warnings: tuple[str, ...] = ()
    related_details: tuple[TabRelatedDetail, ...] = ()
