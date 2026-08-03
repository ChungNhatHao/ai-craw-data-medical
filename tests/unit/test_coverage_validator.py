from datetime import UTC, datetime

from app.models.discovery import DiscoveredItem
from app.models.disease import (
    DiseaseDocument,
    DiseaseFields,
    DiseaseSection,
    DiseaseSource,
    ParseMetadata,
)
from app.models.tabs import DiseaseTabContent, DiseaseTabTable, RawDiseaseTab
from app.plugins.genre_manuals.plugin import GenreManualsPlugin
from app.services.coverage import CoverageValidator

URL = "https://www.genre-manuals.com/diseases/alpha"
HASH = "a" * 64
ITEM = DiscoveredItem(
    item_id="b" * 64,
    source_url=URL,
    canonical_url=URL,
    title_hint="Alpha",
    discovery_page=URL,
)


def _raw_tab(key: str) -> RawDiseaseTab:
    return RawDiseaseTab(
        key=key,
        label=key,
        source_url=URL,
        html=f"<div class='tabContainer'><p>{key} medical guidance</p></div>",
    )


def _clean_tab(key: str) -> DiseaseTabContent:
    return DiseaseTabContent(
        key=key,
        label=key,
        source_url=URL,
        plain_text=f"{key} medical guidance",
        markdown=f"{key} medical guidance",
        content_hash=HASH,
    )


def _document(tabs: tuple[DiseaseTabContent, ...]) -> DiseaseDocument:
    return DiseaseDocument(
        document_id=HASH,
        source=DiseaseSource(
            plugin="genre_manuals",
            url=URL,
            canonical_url=URL,
            retrieved_at=datetime.now(UTC),
            content_hash=HASH,
            language="en",
        ),
        disease=DiseaseFields(name="Alpha"),
        sections=(
            DiseaseSection(
                heading="Alpha",
                level=1,
                order=1,
                markdown="Alpha medical source content",
            ),
        ),
        tabs=tabs,
        parse_metadata=ParseMetadata(
            method="rules",
            parser_version="test",
        ),
    )


def test_coverage_accepts_only_when_all_source_tabs_are_mapped() -> None:
    keys = ("info", "life_dd_tpd", "ip", "health")
    raw = tuple(_raw_tab(key) for key in keys)
    clean = tuple(_clean_tab(key) for key in keys)

    result = CoverageValidator().validate(
        plugin=GenreManualsPlugin(base_url=URL),
        item=ITEM,
        raw_html="<article>Alpha medical source content</article>",
        raw_tabs=raw,
        clean_tabs=clean,
        document=_document(clean),
    )

    assert result.complete
    assert all(result.checks.values())


def test_coverage_rejects_missing_source_tab_and_missing_structured_field() -> None:
    keys = ("info", "life_dd_tpd", "ip")
    raw = (
        RawDiseaseTab(
            key="info",
            label="info",
            source_url=URL,
            html="<article><h2>Treatment</h2><p>Source treatment.</p></article>",
        ),
        *tuple(_raw_tab(key) for key in keys[1:]),
    )
    clean = tuple(_clean_tab(key) for key in keys)
    document = _document(clean).model_copy(
        update={
            "parse_metadata": ParseMetadata(
                method="rules",
                parser_version="test",
                warnings=("missing_field:treatment",),
            )
        }
    )

    result = CoverageValidator().validate(
        plugin=GenreManualsPlugin(base_url=URL),
        item=ITEM,
        raw_html="<article>Alpha medical source content</article>",
        raw_tabs=raw,
        clean_tabs=clean,
        document=document,
    )

    assert not result.complete
    assert "required_source_tabs_incomplete" in result.blockers
    assert "source_field_not_extracted:treatment" in result.blockers


def test_coverage_treats_optional_field_absent_from_source_as_information() -> None:
    keys = ("info", "life_dd_tpd", "ip", "health")
    raw = tuple(_raw_tab(key) for key in keys)
    clean = tuple(_clean_tab(key) for key in keys)
    document = _document(clean).model_copy(
        update={
            "parse_metadata": ParseMetadata(
                method="rules",
                parser_version="test",
                warnings=("missing_field:prevention",),
            )
        }
    )

    result = CoverageValidator().validate(
        plugin=GenreManualsPlugin(base_url=URL),
        item=ITEM,
        raw_html="<article>Alpha medical source content</article>",
        raw_tabs=raw,
        clean_tabs=clean,
        document=document,
    )

    assert result.complete
    assert result.warnings == ("field_not_present_in_source:prevention",)


def test_coverage_ignores_hidden_rows_and_dom_only_spacing() -> None:
    keys = ("info", "life_dd_tpd", "ip", "health")
    raw = tuple(_raw_tab(key) for key in keys)
    raw = (
        raw[0],
        raw[1].model_copy(
            update={
                "html": (
                    "<table><tr aria-hidden='true'><td></td><td></td></tr>"
                    "<tr><td>BMI</td><td>40 kg/m <sup>2</sup></td></tr></table>"
                )
            }
        ),
        raw[2],
        raw[3],
    )
    clean = tuple(_clean_tab(key) for key in keys)
    clean = (
        clean[0],
        clean[1].model_copy(
            update={
                "tables": (
                    DiseaseTabTable(rows=(("BMI", "40 kg/m2"),)),
                )
            }
        ),
        clean[2],
        clean[3],
    )

    result = CoverageValidator().validate(
        plugin=GenreManualsPlugin(base_url=URL),
        item=ITEM,
        raw_html="<article>Alpha medical source content</article>",
        raw_tabs=raw,
        clean_tabs=clean,
        document=_document(clean),
    )

    assert result.complete
