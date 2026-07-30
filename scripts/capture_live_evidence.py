from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from playwright.async_api import Locator, Page

from app.browser.manager import BrowserManager
from app.browser.session import SessionStore
from app.core.config import Settings
from app.plugins.genre_manuals import selectors
from app.plugins.genre_manuals.plugin import GenreManualsPlugin
from app.services.session import SessionService

AUDIT_PATH = Path("output/audits/CURRENT_OUTPUT_ACCURACY_AUDIT.json")
EVIDENCE_ROOT = Path("output/audits/live-evidence")


def slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return normalized[:80] or "disease"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def short_excerpt(value: str, limit: int = 15) -> str:
    return " ".join(value.split()[:limit])


async def first_prose_paragraph(page: Page) -> Locator | None:
    # Do not append ``p`` to CONTENT_ROOT: it is a comma-separated selector and
    # would make the first branch match the whole .genrearticle element.
    paragraphs = page.locator(".genrearticle .intro > p")
    for index in range(await paragraphs.count()):
        paragraph = paragraphs.nth(index)
        outside_table = await paragraph.evaluate(
            "(element) => element.closest('table') === null"
        )
        if outside_table and (await paragraph.inner_text()).strip():
            return paragraph
    return None


async def source_locator(
    page: Page,
    field: str,
) -> tuple[Locator | None, str]:
    if field == "diagnosis":
        locator = page.locator(".genrearticle tr").filter(
            has_text=re.compile(r"supportive evidence", re.IGNORECASE)
        ).first
        return (
            (locator if await locator.count() else None),
            "table row containing Supportive evidence",
        )
    if field == "summary":
        return await first_prose_paragraph(page), "first prose paragraph outside tables"
    if field == "aliases":
        locator = page.get_by_text(
            re.compile(
                r"Paroxysmal ventricular tachycardia.*Paroxysmal tachycardia",
                re.IGNORECASE,
            )
        ).first
        return (
            (locator if await locator.count() else None),
            "pre-table alias text",
        )
    return None, f"unsupported evidence locator for {field}"


async def clipped_screenshot(
    page: Page,
    locator: Locator,
    path: Path,
) -> dict[str, Any]:
    await locator.scroll_into_view_if_needed()
    box = await locator.bounding_box()
    if box is None:
        raise RuntimeError("Evidence locator has no visible bounding box")
    clip = {
        "x": max(0.0, box["x"]),
        "y": max(0.0, box["y"]),
        "width": min(box["width"], 1_300.0),
        "height": min(box["height"], 72.0),
    }
    await page.screenshot(
        path=path,
        type="png",
        clip=clip,
        animations="disabled",
    )
    text = " ".join((await locator.inner_text()).split())
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "text_word_count": len(text.split()),
        "excerpt": short_excerpt(text),
        "clip": clip,
    }


def artifact_dir(
    connection: sqlite3.Connection,
    job_id: str,
    item_id: str,
) -> Path:
    row = connection.execute(
        """
        SELECT artifact_dir
        FROM crawl_items
        WHERE job_id = ? AND item_id = ?
        """,
        (job_id, item_id),
    ).fetchone()
    if row is None or row[0] is None:
        raise RuntimeError(f"Missing artifact directory: {job_id}/{item_id}")
    return Path("output") / row[0]


async def collect() -> dict[str, Any]:
    settings = Settings()
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))  # noqa: ASYNC240
    plugin = GenreManualsPlugin(
        base_url=str(settings.genre_manuals_base_url),
        navigation_timeout_ms=settings.browser_navigation_timeout_ms,
        selector_timeout_ms=settings.browser_selector_timeout_ms,
        detail_confidence_threshold=(
            settings.disease_detail_confidence_threshold
        ),
    )
    EVIDENCE_ROOT.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
    connection = sqlite3.connect(settings.database_path)
    credentials = settings.require_genre_manuals_credentials()
    session_store = SessionStore(
        settings.session_root / "genre_manuals.json"
    )
    records: list[dict[str, Any]] = []
    async with BrowserManager(headless=settings.browser_headless) as manager:
        await SessionService(plugin, session_store).ensure_authenticated(
            manager.browser,
            credentials,
        )
        context = await manager.browser.new_context(
            storage_state=session_store.load()
        )
        page = await context.new_page()
        try:
            for index, item in enumerate(audit["items"], start=1):
                title = item["title"]
                print(f"[evidence {index}/24] {title}", flush=True)
                item_dir = EVIDENCE_ROOT / slug(title)
                item_dir.mkdir(parents=True, exist_ok=True)
                response = await page.goto(
                    item["url"],
                    wait_until="domcontentloaded",
                    timeout=settings.browser_navigation_timeout_ms,
                )
                if response is None:
                    raise RuntimeError(f"No HTTP response for {item['url']}")
                await plugin.dismiss_known_popups(page)
                await plugin.wait_for_detail_content(page)
                classification = await plugin.classify_page(page)
                title_locator = page.locator(selectors.PAGE_TITLE).first
                title_evidence = await clipped_screenshot(
                    page,
                    title_locator,
                    item_dir / "source-title.png",
                )
                disease_dir = artifact_dir(
                    connection,
                    item["job_id"],
                    item["item_id"],
                )
                document = json.loads(
                    (disease_dir / "disease.json").read_text(encoding="utf-8")
                )
                field_evidence: list[dict[str, Any]] = []
                excerpt_used = False
                for field in item["missing_source_fields"]:
                    locator, locator_description = await source_locator(
                        page,
                        field,
                    )
                    evidence: dict[str, Any] = {
                        "field": field,
                        "locator": locator_description,
                        "output_value": document["disease"].get(field),
                    }
                    if locator is None:
                        evidence["capture_error"] = "source locator not found"
                    else:
                        capture = await clipped_screenshot(
                            page,
                            locator,
                            item_dir / f"source-{field}.png",
                        )
                        if excerpt_used:
                            capture["excerpt"] = None
                        else:
                            excerpt_used = True
                        evidence["capture"] = capture
                    field_evidence.append(evidence)

                raw_tabs = await plugin.capture_detail_tabs(page)
                live_tab_evidence = [
                    {
                        "key": tab.key,
                        "available": tab.available,
                        "source_url": str(tab.source_url),
                        "html_sha256": (
                            hashlib.sha256(
                                tab.html.encode("utf-8")
                            ).hexdigest()
                            if tab.html
                            else None
                        ),
                        "related_detail_count": len(tab.related_details),
                    }
                    for tab in raw_tabs
                ]
                live = item["live"]
                records.append(
                    {
                        "title": title,
                        "url": item["url"],
                        "checked_at": datetime.now(UTC).isoformat(),
                        "http_status": response.status,
                        "final_url": page.url,
                        "page_type": classification.page_type.value,
                        "confidence": classification.confidence,
                        "source_title": (
                            " ".join((await title_locator.inner_text()).split())
                        ),
                        "title_evidence": title_evidence,
                        "field_evidence": field_evidence,
                        "output": {
                            "job_id": item["job_id"],
                            "item_id": item["item_id"],
                            "disease_json": str(
                                disease_dir / "disease.json"
                            ),
                            "disease_json_sha256": sha256_file(
                                disease_dir / "disease.json"
                            ),
                            "missing_required_artifacts": item[
                                "missing_required_artifacts"
                            ],
                        },
                        "live_tabs": live_tab_evidence,
                        "semantic_component_matches": live[
                            "component_matches"
                        ],
                        "live_snapshot_match": live["snapshot_match"],
                        "structured_atoms": {
                            "supported": live["supported_atoms"],
                            "total": live["total_atoms"],
                        },
                    }
                )
        finally:
            await context.close()
            connection.close()
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "source_audit": str(AUDIT_PATH),
        "scope": {
            "diseases": len(records),
            "live_http_200": sum(
                record["http_status"] == 200 for record in records
            ),
            "disease_detail_pages": sum(
                record["page_type"] == "disease_detail"
                for record in records
            ),
            "field_exceptions_with_capture": sum(
                bool(record["field_evidence"]) for record in records
            ),
        },
        "items": records,
    }


def markdown_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Hồ sơ bằng chứng thực tế — AI Medical Crawler",
        "",
        f"- Thu thập: `{payload['generated_at']}`",
        f"- URL kiểm tra: **{payload['scope']['diseases']}**",
        f"- HTTP 200: **{payload['scope']['live_http_200']}**",
        (
            "- Xác minh disease detail: "
            f"**{payload['scope']['disease_detail_pages']}**"
        ),
        "",
        "## Ma trận kiểm tra live",
        "",
        "| Bệnh | HTTP | Page type | Structured | Main + 4 tab | Ảnh title |",
        "|---|---:|---|---:|---:|---|",
    ]
    for item in payload["items"]:
        matches = item["semantic_component_matches"]
        relative_title = Path(item["title_evidence"]["path"]).relative_to(
            EVIDENCE_ROOT
        )
        lines.append(
            "| [{title}]({url}) | {status} | {page_type} ({confidence:.2f}) | "
            "{supported}/{total} | {matched}/{component_total} | "
            "[PNG]({png}) |".format(
                title=str(item["title"]).replace("|", "\\|"),
                url=item["url"],
                status=item["http_status"],
                page_type=item["page_type"],
                confidence=item["confidence"],
                supported=item["structured_atoms"]["supported"],
                total=item["structured_atoms"]["total"],
                matched=sum(matches.values()),
                component_total=len(matches),
                png=relative_title.as_posix(),
            )
        )
    lines.extend(
        [
            "",
            "## Bằng chứng cụ thể cho field bị thiếu",
            "",
            "Mỗi mục dưới đây đối chiếu vùng nguồn live với giá trị đang có trong",
            "`disease.json`. Ảnh chỉ chụp vùng nội dung, không chụp account/header.",
            "",
        ]
    )
    for item in payload["items"]:
        if not item["field_evidence"]:
            continue
        lines.extend(
            [
                f"### {item['title']}",
                "",
                f"- URL: {item['url']}",
                f"- Output: `{item['output']['disease_json']}`",
                (
                    "- SHA-256 disease JSON: "
                    f"`{item['output']['disease_json_sha256']}`"
                ),
            ]
        )
        for evidence in item["field_evidence"]:
            output_value = json.dumps(
                evidence["output_value"],
                ensure_ascii=False,
            )
            lines.append(
                f"- Field `{evidence['field']}` trong output: `{output_value}`"
            )
            lines.append(f"  - Locator nguồn: {evidence['locator']}")
            capture = evidence.get("capture")
            if capture is None:
                lines.append(
                    f"  - Lỗi capture: `{evidence.get('capture_error')}`"
                )
                continue
            relative = Path(capture["path"]).relative_to(EVIDENCE_ROOT)
            lines.append(f"  - Ảnh nguồn: [PNG]({relative.as_posix()})")
            lines.append(f"  - SHA-256 ảnh: `{capture['sha256']}`")
            if capture.get("excerpt"):
                lines.append(
                    f"  - Trích đoạn ngắn: “{capture['excerpt']}”"
                )
        lines.append("")
    lines.extend(
        [
            "## Kiểm chứng file",
            "",
            "Mỗi ảnh có SHA-256 trong JSON để phát hiện thay đổi. Hồ sơ không lưu",
            "username, password, cookie, storage state hoặc Gemini API key.",
            "",
        ]
    )
    return "\n".join(lines)


async def main() -> None:
    payload = await collect()
    json_path = EVIDENCE_ROOT / "LIVE_EVIDENCE.json"
    markdown_path = EVIDENCE_ROOT / "LIVE_EVIDENCE.md"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(markdown_report(payload), encoding="utf-8")
    print(json.dumps(payload["scope"], ensure_ascii=False, indent=2))
    print(f"JSON={json_path}")
    print(f"MARKDOWN={markdown_path}")


if __name__ == "__main__":
    asyncio.run(main())
