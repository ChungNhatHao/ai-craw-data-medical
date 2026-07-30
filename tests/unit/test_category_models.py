import pytest
from pydantic import ValidationError

from app.models.category import (
    CATEGORY_REASON_ACTIONS_VI,
    CATEGORY_REASON_VI,
    CategoryDiscoveryNode,
    CategoryNodeStatus,
    CategoryReasonCode,
)
from app.models.navigation import PageType


def test_category_node_round_trip_includes_vietnamese_audit_guidance() -> None:
    node = CategoryDiscoveryNode(
        root_query="Cardiac arrhythmia",
        label="Atrial fibrillation",
        url="https://www.genre-manuals.com/en_atrial_fibrillation.htm",
        canonical_url=(
            "https://www.genre-manuals.com/en_atrial_fibrillation.htm"
        ),
        parent_url=(
            "https://www.genre-manuals.com/en_cardiac_arrhythmias.htm"
        ),
        menu_path=("Cardiac arrhythmias", "Atrial fibrillation"),
        depth=1,
        page_type=PageType.DISEASE_DETAIL,
        confidence=1,
        status=CategoryNodeStatus.CONFIRMED,
        reason_code=CategoryReasonCode.DISEASE_DETAIL_CONFIRMED,
    )

    restored = CategoryDiscoveryNode.model_validate_json(node.model_dump_json())

    assert restored == node
    assert restored.reason_vi
    assert restored.action_steps_vi
    assert set(CATEGORY_REASON_VI) == set(CategoryReasonCode)
    assert set(CATEGORY_REASON_ACTIONS_VI) == set(CategoryReasonCode)


def test_category_node_rejects_inconsistent_path_and_parent() -> None:
    base = {
        "root_query": "Cardiac arrhythmia",
        "label": "Atrial fibrillation",
        "url": "https://www.genre-manuals.com/en_atrial_fibrillation.htm",
        "canonical_url": (
            "https://www.genre-manuals.com/en_atrial_fibrillation.htm"
        ),
        "menu_path": ("Cardiac arrhythmias", "Atrial fibrillation"),
        "depth": 1,
        "page_type": PageType.DISEASE_DETAIL,
        "confidence": 1,
        "status": CategoryNodeStatus.CONFIRMED,
        "reason_code": CategoryReasonCode.DISEASE_DETAIL_CONFIRMED,
    }

    with pytest.raises(ValidationError, match="parent_url"):
        CategoryDiscoveryNode.model_validate(base)
    with pytest.raises(ValidationError, match="depth"):
        CategoryDiscoveryNode.model_validate(
            {
                **base,
                "parent_url": (
                    "https://www.genre-manuals.com/"
                    "en_cardiac_arrhythmias.htm"
                ),
                "depth": 2,
            }
        )
