from app.parser.menu import extract_menu_hierarchy


def test_extract_menu_hierarchy_preserves_home_to_disease_levels() -> None:
    html = """
    <html><body>
      <ul class="breadcrumb">
        <li><a href="/sites/CLUE/home.html">Home</a></li>
        <li><a href="/sites/CLUE/home/page7.html">Medical</a></li>
        <li><a href="/ratings.html">Ratings</a></li>
        <li><a href="/heart.html">Heart</a></li>
        <li>Atrial fibrillation</li>
      </ul>
    </body></html>
    """

    hierarchy = extract_menu_hierarchy(
        html,
        page_url="https://www.genre-manuals.com/en_atrial_fibrillation.htm",
        current_label="Atrial fibrillation",
        canonicalize_url=lambda value: value,
    )

    assert tuple(value.label for value in hierarchy) == (
        "Home",
        "Medical",
        "Ratings",
        "Heart",
        "Atrial fibrillation",
    )
    assert tuple(value.level for value in hierarchy) == (0, 1, 2, 3, 4)
    assert tuple(value.distance_from_disease for value in hierarchy) == (
        4,
        3,
        2,
        1,
        0,
    )
    assert hierarchy[-1].is_current
    assert str(hierarchy[-1].url) == (
        "https://www.genre-manuals.com/en_atrial_fibrillation.htm"
    )
    assert not any(value.is_current for value in hierarchy[:-1])


def test_extract_menu_hierarchy_appends_current_disease_when_missing() -> None:
    hierarchy = extract_menu_hierarchy(
        """
        <ul class="breadcrumb">
          <li><a href="/">Home</a></li>
          <li><a href="/medical.html">Medical</a></li>
        </ul>
        """,
        page_url="https://example.test/disease.html",
        current_label="Example disease",
        canonicalize_url=lambda value: value,
    )

    assert tuple(value.label for value in hierarchy) == (
        "Home",
        "Medical",
        "Example disease",
    )
    assert hierarchy[-1].distance_from_disease == 0
    assert hierarchy[-1].is_current


def test_extract_menu_hierarchy_returns_empty_without_breadcrumb() -> None:
    assert (
        extract_menu_hierarchy(
            "<main>Example disease</main>",
            page_url="https://example.test/disease.html",
            current_label="Example disease",
            canonicalize_url=lambda value: value,
        )
        == ()
    )
