from app.core.ids import build_item_id
from app.plugins.genre_manuals.plugin import GenreManualsPlugin


def test_canonical_url_removes_tracking_fragment_and_sorts_query() -> None:
    plugin = GenreManualsPlugin(
        base_url="https://www.genre-manuals.com/sites/CLUE/home.html"
    )

    canonical = plugin.canonicalize_url(
        "HTTPS://WWW.GENRE-MANUALS.COM/en_med_asthma.htm/"
        "?utm_source=test&b=2&a=1#section"
    )

    assert canonical == (
        "https://www.genre-manuals.com/en_med_asthma.htm?a=1&b=2"
    )


def test_item_id_is_stable_and_plugin_scoped() -> None:
    url = "https://www.genre-manuals.com/en_med_asthma.htm"

    first = build_item_id("genre_manuals", url)
    second = build_item_id("genre_manuals", url)
    other_plugin = build_item_id("other", url)

    assert len(first) == 64
    assert first == second
    assert first != other_plugin


def test_related_detail_targets_exclude_write_actions_and_external_urls() -> None:
    plugin = GenreManualsPlugin(
        base_url="https://www.genre-manuals.com/sites/CLUE/home.html"
    )
    html = """
    <div>
      <a class="genrePopup" href="/life_insurance.htm">Life</a>
      <a class="genrePopup" href="/life_insurance.htm">Life duplicate</a>
      <a class="genrePopup" href="/en_hereditarythoraort.htm">
        Hereditary thoracic aortic disease
      </a>
      <a class="genrePopup" href="/edit.htm">Edit</a>
      <a class="genrePopup" href="/edit-note.htm">Edit note</a>
      <a class="genrePopup" href="https://example.org/other">External</a>
      <input type="button" value="+" onclick="shoppingCartAction()" />
    </div>
    """

    targets = plugin._related_detail_targets(
        html,
        base_url="https://www.genre-manuals.com/en_med_example.htm",
    )

    assert targets == (
        (
            "https://www.genre-manuals.com/life_insurance.htm",
            "Life",
        ),
        (
            "https://www.genre-manuals.com/en_hereditarythoraort.htm",
            "Hereditary thoracic aortic disease",
        ),
    )


def test_related_content_fragment_excludes_navigation_and_account_content() -> None:
    html = """
    <html><body>
      <div id="genre-shortcuts">Account name</div>
      <h2 class="pageTitle">Life Insurance</h2>
      <div class="genrearticle"><p>Underwriting content.</p></div>
    </body></html>
    """

    fragment = GenreManualsPlugin._related_content_fragment(html)

    assert "Life Insurance" in fragment
    assert "Underwriting content" in fragment
    assert "Account name" not in fragment
