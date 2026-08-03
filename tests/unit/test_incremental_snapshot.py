from app.models.tabs import (
    ClassificationRow,
    DiseaseClassificationTable,
    DiseaseTabContent,
    DiseaseTabTable,
    TabRelatedDetail,
)
from app.services.incremental import (
    changed_components,
    snapshot_components,
    snapshot_hash,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
SOURCE = "https://example.test/disease"


def _tab(key: str, digest: str) -> DiseaseTabContent:
    return DiseaseTabContent(
        key=key,
        label=key,
        source_url=SOURCE,
        content_hash=digest,
        tables=(DiseaseTabTable(rows=(("Class", "A"),)),),
        related_details=(
            TabRelatedDetail(
                label="Detail",
                url=f"{SOURCE}/{key}",
                content_hash=digest,
            ),
        ),
    )


def test_snapshot_is_stable_when_tab_order_changes() -> None:
    tabs = (_tab("info", HASH_A), _tab("health", HASH_B))

    first = snapshot_components(HASH_A, tabs)
    second = snapshot_components(HASH_A, tuple(reversed(tabs)))

    assert first == second
    assert snapshot_hash(first) == snapshot_hash(second)


def test_snapshot_detects_a_single_tab_change() -> None:
    before = snapshot_components(HASH_A, (_tab("info", HASH_A),))
    after = snapshot_components(HASH_A, (_tab("info", HASH_B),))

    assert snapshot_hash(before) != snapshot_hash(after)
    assert changed_components(after, before) == ("tab:info",)


def test_snapshot_detects_a_classification_level_change() -> None:
    root = ClassificationRow(
        classification_id=HASH_A,
        classification="Root",
        level=0,
        classification_path=("Root",),
        is_group=True,
    )
    child = ClassificationRow(
        classification_id=HASH_B,
        parent_classification_id=HASH_A,
        parent_classification="Root",
        classification="Child",
        level=1,
        classification_path=("Root", "Child"),
        is_group=False,
    )
    hierarchical = _tab("health", HASH_A).model_copy(
        update={
            "classification_table": DiseaseClassificationTable(
                rows=(root, child),
            )
        }
    )
    flat = _tab("health", HASH_A).model_copy(
        update={
            "classification_table": DiseaseClassificationTable(
                rows=(
                    root,
                    child.model_copy(
                        update={
                            "parent_classification_id": None,
                            "parent_classification": None,
                            "level": 0,
                            "classification_path": ("Child",),
                        }
                    ),
                ),
            )
        }
    )

    before = snapshot_components(HASH_A, (flat,))
    after = snapshot_components(HASH_A, (hierarchical,))

    assert before["tab:health"] != after["tab:health"]
