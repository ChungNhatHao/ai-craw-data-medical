import json
import os
import tempfile
from pathlib import Path

from playwright.async_api import Page

from app.models.discovery import DiscoveredItem, DiscoveryPolicy, DiscoveryResult
from app.plugins.base import SitePlugin
from app.repositories.items import ItemRepository


class DiscoveryService:
    def __init__(
        self,
        plugin: SitePlugin,
        items: ItemRepository,
        output_root: Path,
        policy: DiscoveryPolicy,
    ) -> None:
        self.plugin = plugin
        self.items = items
        self.output_root = output_root
        self.policy = policy

    async def run(self, page: Page, job_id: str) -> DiscoveryResult:
        discovered: dict[str, DiscoveredItem] = {}
        visited_pages: set[str] = set()
        no_new_rounds = 0
        limits: list[str] = []
        stopped_reason = "last_page"

        for _ in range(self.policy.max_pages):
            current_page = self.plugin.canonicalize_url(page.url)
            if current_page in visited_pages:
                stopped_reason = "repeated_page"
                break
            visited_pages.add(current_page)

            page_items = await self.plugin.discover_items(page)
            new_items = [
                item for item in page_items if item.item_id not in discovered
            ]
            accepted_items: list[DiscoveredItem] = []
            for item in new_items:
                if len(discovered) >= self.policy.max_items:
                    limits.append("max_items")
                    stopped_reason = "max_items"
                    break
                discovered[item.item_id] = item
                accepted_items.append(item)
            await self.items.upsert_discovered(job_id, accepted_items)

            if len(discovered) >= self.policy.max_items:
                if "max_items" not in limits and len(new_items) > len(accepted_items):
                    limits.append("max_items")
                    stopped_reason = "max_items"
                break
            no_new_rounds = 0 if new_items else no_new_rounds + 1
            if no_new_rounds >= self.policy.max_no_new_rounds:
                stopped_reason = "no_new_items"
                break

            candidate = await self.plugin.find_next_listing_page(
                page,
                frozenset(visited_pages),
            )
            if candidate is None:
                stopped_reason = "last_page"
                break
            await self.plugin.navigate_to_candidate(page, candidate)
        else:
            limits.append("max_pages")
            stopped_reason = "max_pages"

        persisted = await self.items.list_for_job(job_id)
        self._export(job_id, persisted)
        return DiscoveryResult(
            items=tuple(persisted),
            pages_visited=len(visited_pages),
            stopped_reason=stopped_reason,
            limits_reached=tuple(limits),
        )

    def _export(self, job_id: str, items: list[DiscoveredItem]) -> None:
        job_output = self.output_root / "jobs" / job_id
        job_output.mkdir(parents=True, exist_ok=True)
        target = job_output / "disease-list.json"
        temporary_path: Path | None = None
        payload = {
            "job_id": job_id,
            "count": len(items),
            "items": [item.model_dump(mode="json") for item in items],
        }
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=job_output,
                prefix=".disease-list.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                json.dump(payload, temporary, ensure_ascii=False, indent=2)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, target)
        except Exception:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise

    async def export_snapshot(self, job_id: str) -> list[DiscoveredItem]:
        items = await self.items.list_for_job(job_id)
        self._export(job_id, items)
        return items
