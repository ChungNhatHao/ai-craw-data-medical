from app.models.tabs import (
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
