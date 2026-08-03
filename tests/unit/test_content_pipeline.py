from pathlib import Path

from app.parser.extractor import ContentExtractor
from app.parser.markdown import MarkdownConverter, content_hash, normalize_markdown
from app.plugins.genre_manuals.plugin import GenreManualsPlugin

FIXTURE = Path("tests/fixtures/genre_manuals/disease_content_complex.html")
BASE_URL = "https://www.genre-manuals.com/en_complex_disease.htm"


def make_plugin() -> GenreManualsPlugin:
    return GenreManualsPlugin(base_url=BASE_URL)


def test_extract_and_convert_preserves_structure_without_boilerplate() -> None:
    plugin = make_plugin()
    extracted = ContentExtractor(minimum_chars=50).extract(
        FIXTURE.read_text(encoding="utf-8"),
        root_selectors=plugin.content_root_selectors(),
        title_selectors=plugin.content_title_selectors(),
    )
    markdown, warnings = MarkdownConverter(plugin.canonicalize_url).convert(
        extracted.html,
        base_url=BASE_URL,
    )

    assert "Account header must be removed" not in extracted.html
    assert "Disease menu must be removed" not in extracted.html
    assert "Footer must be removed" not in extracted.html
    assert "secretMenuState" not in extracted.html
    assert "# Complex disease" in markdown
    assert "### Overview" in markdown
    assert "- First symptom" in markdown
    assert "  1. Nested qualifier" in markdown
    assert "| Band | Value |" in markdown
    assert "| Low | 1 |" in markdown
    assert (
        "[evidence link](https://www.genre-manuals.com/evidence.htm)"
        in markdown
    )
    assert warnings == ()


def test_generic_content_root_fallback_is_reported() -> None:
    html = """
    <html><body><main><h1>Fallback disease</h1>
    <p>This main content is intentionally long enough for deterministic
    generic extraction when the plugin selector does not match the page.</p>
    </main></body></html>
    """

    extracted = ContentExtractor(minimum_chars=50).extract(
        html,
        root_selectors=(".missing-plugin-root",),
        title_selectors=("h1",),
    )

    assert "generic_content_root_fallback" in extracted.warnings
    assert "Fallback disease" in extracted.html


def test_markdown_normalization_and_content_hash_are_deterministic() -> None:
    composed = "# Café\r\n\r\n\r\nText   \r\n"
    decomposed = "# Cafe\u0301\n\nText\n"

    assert normalize_markdown(composed) == normalize_markdown(decomposed)
    assert content_hash(composed) == content_hash(decomposed)


def test_markdown_converter_omits_empty_table_without_leaking_html() -> None:
    plugin = make_plugin()
    markdown, warnings = MarkdownConverter(plugin.canonicalize_url).convert(
        """
        <article>
          <h1>Multiple and mixed valvular heart disease</h1>
          <p>Clinical description.</p>
          <table></table>
        </article>
        """,
        base_url=BASE_URL,
    )

    assert "<table" not in markdown
    assert "</table>" not in markdown
    assert "Clinical description." in markdown
    assert warnings == ("empty_table_omitted",)


def test_markdown_table_uses_plain_text_for_multiline_cells() -> None:
    plugin = make_plugin()
    markdown, warnings = MarkdownConverter(plugin.canonicalize_url).convert(
        """
        <article><table>
          <tr><th>Evidence</th><th>Details</th></tr>
          <tr><td>Report<br>ECG</td><td>Required</td></tr>
        </table></article>
        """,
        base_url=BASE_URL,
    )

    assert "| Report / ECG | Required |" in markdown
    assert "<br>" not in markdown
    assert warnings == ()
