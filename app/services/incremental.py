import hashlib
import json

from app.models.tabs import DiseaseTabContent


def snapshot_components(
    content_hash: str,
    tabs: tuple[DiseaseTabContent, ...],
) -> dict[str, str]:
    components = {"main": content_hash}
    for tab in sorted(tabs, key=lambda value: value.key):
        payload = {
            "available": tab.available,
            "content_hash": tab.content_hash,
            "tables": [
                [list(row) for row in table.rows]
                for table in tab.tables
            ],
            "related_details": [
                {
                    "label": detail.label,
                    "url": str(detail.url),
                    "available": detail.available,
                    "content_hash": detail.content_hash,
                }
                for detail in sorted(
                    tab.related_details,
                    key=lambda value: (str(value.url), value.label),
                )
            ],
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        components[f"tab:{tab.key}"] = hashlib.sha256(encoded).hexdigest()
    return components


def snapshot_hash(components: dict[str, str]) -> str:
    encoded = json.dumps(
        components,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def changed_components(
    current: dict[str, str],
    previous: dict[str, str],
) -> tuple[str, ...]:
    return tuple(
        key
        for key in sorted(current.keys() | previous.keys())
        if current.get(key) != previous.get(key)
    )
