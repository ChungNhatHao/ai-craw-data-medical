from typing import Literal

from pydantic import BaseModel, Field, HttpUrl

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


class DiseaseTabContent(BaseModel):
    key: TabKey
    label: str = Field(min_length=1)
    source_url: HttpUrl
    available: bool = True
    plain_text: str = ""
    markdown: str = ""
    tables: tuple[DiseaseTabTable, ...] = ()
    content_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    warnings: tuple[str, ...] = ()
    related_details: tuple[TabRelatedDetail, ...] = ()
