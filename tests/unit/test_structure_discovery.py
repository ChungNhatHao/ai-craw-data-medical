from app.models.tabs import RawDiseaseTab
from app.services.structure_discovery import SiteStructureProfiler

URL = "https://example.test/diseases/alpha"


def _tab(key: str) -> RawDiseaseTab:
    return RawDiseaseTab(
        key=key,
        label=key,
        source_url=URL,
        html=f"<div class='tabContainer'><p>{key} source content</p></div>",
    )


def test_profiler_detects_roots_tables_tabs_and_dynamic_content() -> None:
    html = """
    <html><head><title>Alpha disease</title></head><body>
      <main><h1>Alpha disease</h1><p>This is representative medical content
      with enough text for conservative content-root detection.</p></main>
      <div id="app"></div>
      <button role="tab">Health</button>
      <table id="ratings"><tr><th>Classification</th><th>Life</th></tr>
        <tr><td>All cases</td><td>+50</td></tr></table>
      <a href="/diseases/beta">Beta</a>
    </body></html>
    """

    profile = SiteStructureProfiler().analyze_page(html, url=URL)

    assert "main" in profile.content_root_candidates
    assert profile.tables[0].selector == "table#ratings"
    assert profile.tables[0].row_count == 2
    assert profile.tab_labels == ("Health",)
    assert profile.same_origin_link_count == 1
    assert "client_rendered_app" in profile.dynamic_markers


def test_site_profile_fails_closed_when_a_required_tab_is_missing() -> None:
    html = "<main>" + ("Medical detail content. " * 5) + "</main>"
    tabs = tuple(_tab(key) for key in ("info", "life_dd_tpd", "ip"))

    profile = SiteStructureProfiler().build_profile(
        plugin="adaptive",
        html=html,
        url=URL,
        tabs=tabs,
        required_tabs=("info", "life_dd_tpd", "ip", "health"),
    )

    assert not profile.ready
    assert "required_tab_missing:health" in profile.blockers
