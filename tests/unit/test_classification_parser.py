from app.parser.classification import extract_classification_table


def _tab_html(*, rating_header: str, leaf_rating: str) -> str:
    return f"""
    <div class="tabContainer">
      <table class="conditionTableCss floatThead-table">
        <tr>
          <th>Classification</th>
          <th>{rating_header}</th>
          <th>Code</th>
          <th></th>
        </tr>
      </table>
      <table id="conditionTable" class="conditionTableCss">
        <tr aria-hidden="true"><th aria-label="Classification"></th></tr>
        <tr>
          <th class="level-0">Without underlying heart disease</th>
          <td></td><td></td><td></td>
        </tr>
        <tr>
          <th class="level" style="padding-left: 25px">Current</th>
          <td></td><td></td><td></td>
        </tr>
        <tr>
          <th class="level" style="padding-left: 50px">Age at application</th>
          <td></td><td></td><td></td>
        </tr>
        <tr>
          <th class="level" style="padding-left: 75px">≤ 60 years</th>
          <td>{leaf_rating}</td><td>I48.9</td><td></td>
        </tr>
      </table>
    </div>
    """


def test_classification_parser_preserves_levels_paths_ratings_and_tree() -> None:
    table = extract_classification_table(
        _tab_html(rating_header="Life", leaf_rating="+50")
    )

    assert table is not None
    assert table.headers == ("Classification", "Life", "Code")
    assert len(table.rows) == 4
    leaf = table.rows[-1]
    assert leaf.level == 3
    assert leaf.parent_classification == "Age at application"
    assert leaf.parent_classification_id == table.rows[-2].classification_id
    assert leaf.classification_path == (
        "Without underlying heart disease",
        "Current",
        "Age at application",
        "≤ 60 years",
    )
    assert leaf.ratings == {"Life": "+50"}
    assert leaf.code == "I48.9"
    assert not leaf.is_group
    assert table.rows[0].is_group
    assert table.rows[0].parent_classification is None
    assert table.rows[0].parent_classification_id is None
    assert table.tree[0].children[0].children[0].children[0].classification == (
        "≤ 60 years"
    )
    assert table.warnings == ()


def test_classification_id_is_stable_across_product_tabs() -> None:
    life = extract_classification_table(
        _tab_html(rating_header="Life", leaf_rating="+50")
    )
    health = extract_classification_table(
        _tab_html(rating_header="Hospitalisation", leaf_rating="D")
    )

    assert life is not None
    assert health is not None
    assert tuple(row.classification_id for row in life.rows) == tuple(
        row.classification_id for row in health.rows
    )
    assert life.rows[-1].ratings == {"Life": "+50"}
    assert health.rows[-1].ratings == {"Hospitalisation": "D"}


def test_classification_parser_reports_and_repairs_invalid_level_jump() -> None:
    html = """
    <table class="floatThead-table">
      <tr><th>Classification</th><th>Life</th></tr>
    </table>
    <table id="conditionTable">
      <tr><th class="level-0">Root</th><td></td></tr>
      <tr>
        <th class="level" style="padding-left: 50px">Jumped child</th>
        <td>+25</td>
      </tr>
      <tr>
        <th class="level" style="padding-left: 30px">Invalid padding</th>
        <td>+50</td>
      </tr>
    </table>
    """

    table = extract_classification_table(html)

    assert table is not None
    assert table.rows[1].level == 1
    assert "classification_level_jump" in table.warnings
    assert "classification_level_invalid" in table.warnings
