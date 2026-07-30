import json
from pathlib import Path

from app.models.discovery import DiscoveredItem


def load_latest_discovered_items(
    output_root: Path,
    *,
    limit: int,
) -> list[DiscoveredItem]:
    lists = sorted(
        output_root.glob("jobs/*/disease-list.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in lists:
        payload = json.loads(path.read_text(encoding="utf-8"))
        items = payload.get("items", [])
        if items:
            return [
                DiscoveredItem.model_validate(item)
                for item in items[:limit]
            ]
    raise RuntimeError("A non-empty Day 4 disease-list.json is required")


def find_latest_artifact_job(
    output_root: Path,
    *,
    minimum_items: int,
) -> str:
    job_directories = sorted(
        output_root.glob("jobs/*"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for directory in job_directories:
        manifests = list(directory.glob("items/*/manifest.json"))
        if len(manifests) >= minimum_items:
            return directory.name
    raise RuntimeError(
        f"A job with at least {minimum_items} raw artifact sets is required"
    )
