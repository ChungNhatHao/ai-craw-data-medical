from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from app.browser.manager import BrowserManager
from app.browser.session import SessionStore
from app.core.config import Settings
from app.models.artifacts import RawArtifactManifest
from app.models.discovery import DiscoveredItem
from app.models.disease import DiseaseDocument
from app.models.tabs import DiseaseTabContent, RawDiseaseTab
from app.parser.chunks import chunk_by_heading
from app.parser.extractor import ContentExtractor
from app.parser.markdown import MarkdownConverter, content_hash
from app.plugins.genre_manuals.plugin import GenreManualsPlugin
from app.repositories.attempts import AttemptRepository
from app.repositories.database import Database
from app.repositories.items import ItemRepository
from app.services.cleaning import CLEANER_VERSION, CleaningService
from app.services.incremental import snapshot_components, snapshot_hash
from app.services.session import SessionService
from app.storage.artifacts import ArtifactStore

FIELD_NAMES = (
    "name",
    "aliases",
    "summary",
    "causes",
    "risk_factors",
    "symptoms",
    "diagnosis",
    "treatment",
    "prevention",
    "prognosis",
    "when_to_seek_care",
)
REQUIRED_ARTIFACTS = frozenset(
    {
        "raw_html",
        "screenshot",
        "content_html",
        "markdown",
        "disease_json",
        "tabs_raw",
        "tabs",
    }
)
LIST_FIELDS = frozenset(
    {
        "aliases",
        "causes",
        "risk_factors",
        "symptoms",
        "diagnosis",
        "treatment",
        "prevention",
        "when_to_seek_care",
    }
)
TABLE_LABELS = {
    "cause": "causes",
    "causes": "causes",
    "risk factor": "risk_factors",
    "risk factors": "risk_factors",
    "symptom": "symptoms",
    "symptoms": "symptoms",
    "signs and symptoms": "symptoms",
    "diagnosis": "diagnosis",
    "diagnostic": "diagnosis",
    "supportive evidence": "diagnosis",
    "treatment": "treatment",
    "prevention": "prevention",
    "prognosis": "prognosis",
    "when to seek care": "when_to_seek_care",
}


@dataclass(frozen=True)
class AuditItem:
    job_id: str
    item: DiscoveredItem
    artifact_dir: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit latest unique disease outputs against stored and live source"
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Revisit every authenticated source URL and compare semantic snapshots",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/audits"),
    )
    parser.add_argument(
        "--all-versions",
        action="store_true",
        help="Audit every parsed historical row instead of latest unique diseases",
    )
    parser.add_argument(
        "--reuse-live",
        type=Path,
        help="Reuse per-item live evidence from a previous JSON audit",
    )
    return parser.parse_args()


def normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip(" \t\r\n.,;:")


def short_excerpt(text: str, needle: str, max_words: int = 15) -> str | None:
    normalized_text = normalize(text)
    normalized_needle = normalize(needle)
    index = normalized_text.find(normalized_needle)
    if index < 0:
        return None
    words = text.split()
    needle_words = max(1, len(needle.split()))
    running = 0
    start_word = 0
    for position, word in enumerate(words):
        next_running = running + len(normalize(word)) + (1 if running else 0)
        if next_running > index:
            start_word = max(0, position - 3)
            break
        running = next_running
    return " ".join(words[start_word : start_word + max(max_words, needle_words)])


def percent(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator * 100 / denominator, 2)


def selected_items(
    settings: Settings,
    *,
    all_versions: bool,
) -> list[AuditItem]:
    connection = sqlite3.connect(settings.database_path)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT ci.job_id, ci.item_id, ci.source_url, ci.canonical_url,
                   ci.title_hint, ci.discovery_page, ci.artifact_dir,
                   cj.created_at
            FROM crawl_items AS ci
            JOIN crawl_jobs AS cj ON cj.id = ci.job_id
            WHERE ci.status = 'parsed'
              AND ci.artifact_dir IS NOT NULL
            ORDER BY cj.created_at DESC, ci.updated_at DESC
            """
        ).fetchall()
    finally:
        connection.close()
    seen: set[str] = set()
    selected: list[AuditItem] = []
    for row in rows:
        if not all_versions and row["item_id"] in seen:
            continue
        seen.add(row["item_id"])
        selected.append(
            AuditItem(
                job_id=row["job_id"],
                item=DiscoveredItem(
                    item_id=row["item_id"],
                    source_url=row["source_url"],
                    canonical_url=row["canonical_url"],
                    title_hint=row["title_hint"],
                    discovery_page=row["discovery_page"],
                ),
                artifact_dir=settings.output_root / row["artifact_dir"],
            )
        )
    return selected


def digest_matches(path: Path, expected: str) -> bool:
    try:
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return False
    return actual == expected


def source_text(
    markdown: str,
    tabs: tuple[DiseaseTabContent, ...],
) -> str:
    values = [markdown]
    for tab in tabs:
        values.append(tab.markdown)
        values.extend(detail.markdown for detail in tab.related_details)
    return "\n".join(value for value in values if value)


def atom_values(document: DiseaseDocument) -> list[tuple[str, str]]:
    disease = document.disease.model_dump(mode="python")
    atoms: list[tuple[str, str]] = []
    for field in FIELD_NAMES:
        value = disease.get(field)
        if field in LIST_FIELDS:
            atoms.extend((field, str(item)) for item in value or ())
        elif value:
            atoms.append((field, str(value)))
    return atoms


def draft_quote_map(path: Path) -> dict[tuple[str, str], str]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    quotes: dict[tuple[str, str], str] = {}
    for field in FIELD_NAMES:
        raw = payload.get(field)
        entries = raw if isinstance(raw, list) else [raw]
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            value = entry.get("value")
            quote = entry.get("source_quote")
            if isinstance(value, str) and isinstance(quote, str):
                quotes[(field, normalize(value))] = quote
    return quotes


def expected_source_fields(
    content_html: str,
    markdown: str,
) -> dict[str, str]:
    soup = BeautifulSoup(content_html, "lxml")
    expected = {"name": "h1/page title"}
    prose_paragraph = next(
        (
            paragraph
            for paragraph in soup.find_all("p")
            if paragraph.find_parent("table") is None
        ),
        None,
    )
    if prose_paragraph is not None:
        expected["summary"] = "prose paragraph outside tables"
    lines = [
        line.strip()
        for line in markdown.splitlines()
        if line.strip() and not line.startswith("|")
    ]
    if len(lines) >= 3:
        alias_candidate = lines[2]
        if (
            not alias_candidate.startswith(("-", "#"))
            and (
                "*" in alias_candidate
                or len(alias_candidate.split()) <= 5
            )
        ):
            expected["aliases"] = "pre-table alias line"
    for row in soup.find_all("tr"):
        cells = row.find_all(["th", "td"], recursive=False)
        if not cells:
            continue
        label = normalize(cells[0].get_text(" ", strip=True))
        mapped = TABLE_LABELS.get(label)
        if mapped is not None:
            expected[mapped] = f"table row label: {label}"
    return expected


def populated_fields(document: DiseaseDocument) -> set[str]:
    payload = document.disease.model_dump(mode="python")
    return {field for field in FIELD_NAMES if payload.get(field)}


def offline_item_audit(
    audit_item: AuditItem,
    *,
    artifacts: ArtifactStore,
    cleaning: CleaningService,
) -> tuple[dict[str, Any], str, tuple[DiseaseTabContent, ...]]:
    directory = audit_item.artifact_dir
    manifest = RawArtifactManifest.model_validate_json(
        (directory / "manifest.json").read_bytes()
    )
    artifact_checks = {
        name: digest_matches(directory / digest.name, digest.sha256)
        for name, digest in manifest.artifacts.items()
    }
    document = DiseaseDocument.model_validate_json(
        (directory / "disease.json").read_bytes()
    )
    markdown = (directory / "markdown.md").read_text(encoding="utf-8")
    content_html = (directory / "content.html").read_text(encoding="utf-8")
    raw_html = (directory / "raw.html").read_text(encoding="utf-8")
    raw_tabs_path = directory / "tabs-raw.json"
    tabs_path = directory / "tabs.json"
    raw_tabs = (
        tuple(
            RawDiseaseTab.model_validate(value)
            for value in json.loads(raw_tabs_path.read_text(encoding="utf-8"))
        )
        if raw_tabs_path.exists()
        else ()
    )
    stored_tabs = (
        tuple(
            DiseaseTabContent.model_validate(value)
            for value in json.loads(tabs_path.read_text(encoding="utf-8"))
        )
        if tabs_path.exists()
        else ()
    )

    extracted = cleaning.extractor.extract(
        raw_html,
        root_selectors=cleaning.plugin.content_root_selectors(),
        title_selectors=cleaning.plugin.content_title_selectors(),
    )
    rebuilt_markdown, _ = MarkdownConverter(
        cleaning.plugin.canonicalize_url
    ).convert(
        extracted.html,
        base_url=str(audit_item.item.canonical_url),
    )
    rebuilt_tabs = cleaning._clean_tabs(  # noqa: SLF001
        raw_tabs,
        base_url=str(audit_item.item.canonical_url),
    )
    main_transform_match = (
        extracted.html == content_html
        and rebuilt_markdown == markdown
        and content_hash(markdown) == manifest.content_hash
    )
    tabs_transform_match = [
        {
            "key": stored.key,
            "match": stored == rebuilt,
            "available": stored.available,
            "content_hash": stored.content_hash,
        }
        for stored, rebuilt in zip(stored_tabs, rebuilt_tabs, strict=False)
    ]
    tab_shape_match = (
        len(stored_tabs) == len(rebuilt_tabs)
        and [tab.key for tab in stored_tabs] == [tab.key for tab in rebuilt_tabs]
    )
    combined_source = source_text(markdown, stored_tabs)
    quotes = draft_quote_map(directory / "disease-draft.json")
    atoms: list[dict[str, Any]] = []
    for field, value in atom_values(document):
        exact = normalize(value) in normalize(combined_source)
        quote = quotes.get((field, normalize(value)))
        quote_grounded = bool(
            quote and normalize(quote) in normalize(combined_source)
        )
        atoms.append(
            {
                "field": field,
                "value_hash": hashlib.sha256(
                    normalize(value).encode("utf-8")
                ).hexdigest(),
                "supported": exact or quote_grounded,
                "support_method": (
                    "exact_source_text"
                    if exact
                    else "grounded_source_quote"
                    if quote_grounded
                    else "not_found"
                ),
            }
        )
    evidence_excerpt = next(
        (
            short_excerpt(combined_source, value)
            for field, value in atom_values(document)
            if field == "name"
        ),
        None,
    )
    expected_evidence = expected_source_fields(content_html, markdown)
    expected = set(expected_evidence)
    populated = populated_fields(document)
    component_map = snapshot_components(
        content_hash(markdown),
        stored_tabs,
    )
    sections_match = tuple(
        chunk.as_section() for chunk in chunk_by_heading(markdown)
    ) == document.sections
    return (
        {
            "job_id": audit_item.job_id,
            "item_id": audit_item.item.item_id,
            "title": audit_item.item.title_hint,
            "url": str(audit_item.item.canonical_url),
            "retrieved_at": manifest.retrieved_at.isoformat(),
            "parser": {
                "method": document.parse_metadata.method,
                "model": document.parse_metadata.model,
                "parser_version": document.parse_metadata.parser_version,
                "prompt_version": document.parse_metadata.prompt_version,
            },
            "artifact_checks": artifact_checks,
            "artifact_integrity": all(artifact_checks.values()),
            "required_artifact_set": REQUIRED_ARTIFACTS.issubset(
                manifest.artifacts
            ),
            "missing_required_artifacts": sorted(
                REQUIRED_ARTIFACTS - manifest.artifacts.keys()
            ),
            "main_transform_match": main_transform_match,
            "tabs_transform_match": tab_shape_match
            and all(value["match"] for value in tabs_transform_match),
            "tab_checks": tabs_transform_match,
            "document_tabs_match": document.tabs == stored_tabs,
            "sections_match": sections_match,
            "stored_snapshot_hash": snapshot_hash(component_map),
            "stored_component_hashes": component_map,
            "manifest_snapshot_hash": manifest.snapshot_hash,
            "atoms": atoms,
            "evidence_excerpt": evidence_excerpt,
            "expected_source_fields": sorted(expected),
            "expected_field_evidence": expected_evidence,
            "populated_source_fields": sorted(expected & populated),
            "missing_source_fields": sorted(expected - populated),
            "warnings": list(document.parse_metadata.warnings),
            "live": None,
        },
        markdown,
        stored_tabs,
    )


async def live_audit(
    records: list[tuple[AuditItem, dict[str, Any]]],
    *,
    settings: Settings,
    plugin: GenreManualsPlugin,
    cleaning: CleaningService,
) -> None:
    credentials = settings.require_genre_manuals_credentials()
    store = SessionStore(settings.session_root / "genre_manuals.json")
    async with BrowserManager(headless=settings.browser_headless) as manager:
        await SessionService(plugin, store).ensure_authenticated(
            manager.browser,
            credentials,
        )
        context = await manager.browser.new_context(storage_state=store.load())
        page = await context.new_page()
        try:
            for index, (audit_item, record) in enumerate(records, start=1):
                print(
                    f"[live {index}/{len(records)}] {audit_item.item.title_hint}",
                    flush=True,
                )
                try:
                    response = await page.goto(
                        str(audit_item.item.canonical_url),
                        wait_until="domcontentloaded",
                        timeout=settings.browser_navigation_timeout_ms,
                    )
                    if response is None or response.status >= 400:
                        raise RuntimeError(
                            f"source HTTP status: {response.status if response else 'none'}"
                        )
                    await plugin.dismiss_known_popups(page)
                    classification = await plugin.classify_page(page)
                    await plugin.wait_for_detail_content(page)
                    raw_html = await page.content()
                    raw_tabs = await plugin.capture_detail_tabs(page)
                    extracted = cleaning.extractor.extract(
                        raw_html,
                        root_selectors=plugin.content_root_selectors(),
                        title_selectors=plugin.content_title_selectors(),
                    )
                    markdown, _ = MarkdownConverter(
                        plugin.canonicalize_url
                    ).convert(
                        extracted.html,
                        base_url=str(audit_item.item.canonical_url),
                    )
                    tabs = cleaning._clean_tabs(  # noqa: SLF001
                        raw_tabs,
                        base_url=str(audit_item.item.canonical_url),
                    )
                    live_components = snapshot_components(
                        content_hash(markdown),
                        tabs,
                    )
                    live_snapshot = snapshot_hash(live_components)
                    live_source = source_text(markdown, tabs)
                    live_atoms = []
                    for atom in record["atoms"]:
                        value_hash = atom["value_hash"]
                        matched_value = next(
                            (
                                value
                                for field, value in atom_values(
                                    DiseaseDocument.model_validate_json(
                                        (
                                            audit_item.artifact_dir
                                            / "disease.json"
                                        ).read_bytes()
                                    )
                                )
                                if field == atom["field"]
                                and hashlib.sha256(
                                    normalize(value).encode("utf-8")
                                ).hexdigest()
                                == value_hash
                            ),
                            None,
                        )
                        live_atoms.append(
                            bool(
                                matched_value
                                and normalize(matched_value)
                                in normalize(live_source)
                            )
                        )
                    record["live"] = {
                        "checked_at": datetime.now(UTC).isoformat(),
                        "http_status": response.status,
                        "page_type": classification.page_type.value,
                        "confidence": classification.confidence,
                        "snapshot_hash": live_snapshot,
                        "snapshot_match": (
                            live_snapshot == record["stored_snapshot_hash"]
                        ),
                        "component_matches": {
                            key: value
                            == record["stored_component_hashes"].get(key)
                            for key, value in live_components.items()
                        },
                        "supported_atoms": sum(live_atoms),
                        "total_atoms": len(live_atoms),
                        "error": None,
                    }
                except Exception as exc:
                    record["live"] = {
                        "checked_at": datetime.now(UTC).isoformat(),
                        "error": f"{type(exc).__name__}: {exc}",
                    }
        finally:
            await context.close()


def summarize(
    records: list[dict[str, Any]],
    live_requested: bool,
    *,
    selection_mode: str,
) -> dict[str, Any]:
    artifact_checks = [
        passed
        for record in records
        for passed in record["artifact_checks"].values()
    ]
    atoms = [atom for record in records for atom in record["atoms"]]
    expected_fields = sum(
        len(record["expected_source_fields"]) for record in records
    )
    populated_fields = sum(
        len(record["populated_source_fields"]) for record in records
    )
    semantic_checks = [
        record["main_transform_match"]
        and record["tabs_transform_match"]
        and record["document_tabs_match"]
        and record["sections_match"]
        and record["required_artifact_set"]
        for record in records
    ]
    live_records = [
        record
        for record in records
        if record["live"] is not None and record["live"].get("error") is None
    ]
    live_components = [
        matched
        for record in live_records
        for matched in record["live"]["component_matches"].values()
    ]
    live_atom_supported = sum(
        int(record["live"]["supported_atoms"]) for record in live_records
    )
    live_atom_total = sum(
        int(record["live"]["total_atoms"]) for record in live_records
    )
    offline_atom_supported = sum(atom["supported"] for atom in atoms)
    semantic_supported = (
        live_atom_supported + sum(live_components)
        if live_records
        else offline_atom_supported + sum(semantic_checks)
    )
    semantic_total = (
        live_atom_total + len(live_components)
        if live_records
        else len(atoms) + len(semantic_checks)
    )
    primary_supported = semantic_supported + populated_fields
    primary_total = semantic_total + expected_fields
    return {
        "scope": {
            "selected_outputs": len(records),
            "unique_diseases": len(
                {record["item_id"] for record in records}
            ),
            "selection_mode": selection_mode,
            "live_requested": live_requested,
            "live_checked": len(live_records),
            "live_errors": len(records) - len(live_records)
            if live_requested
            else 0,
        },
        "artifact_integrity": {
            "passed": sum(artifact_checks),
            "total": len(artifact_checks),
            "percent": percent(sum(artifact_checks), len(artifact_checks)),
        },
        "complete_required_artifact_sets": {
            "passed": sum(
                record["required_artifact_set"] for record in records
            ),
            "total": len(records),
            "percent": percent(
                sum(record["required_artifact_set"] for record in records),
                len(records),
            ),
        },
        "deterministic_transform_fidelity": {
            "passed": sum(semantic_checks),
            "total": len(semantic_checks),
            "percent": percent(sum(semantic_checks), len(semantic_checks)),
        },
        "structured_grounding_precision_stored": {
            "supported": offline_atom_supported,
            "total": len(atoms),
            "percent": percent(offline_atom_supported, len(atoms)),
        },
        "source_explicit_field_completeness": {
            "populated": populated_fields,
            "expected": expected_fields,
            "percent": percent(populated_fields, expected_fields),
        },
        "live_semantic_freshness": {
            "matching_components": sum(live_components),
            "total_components": len(live_components),
            "percent": percent(sum(live_components), len(live_components)),
            "matching_full_snapshots": sum(
                bool(record["live"]["snapshot_match"])
                for record in live_records
            ),
            "checked_diseases": len(live_records),
        },
        "live_structured_grounding_precision": {
            "supported": live_atom_supported,
            "total": live_atom_total,
            "percent": percent(live_atom_supported, live_atom_total),
        },
        "semantic_faithfulness": {
            "supported_evidence_units": semantic_supported,
            "total_evidence_units": semantic_total,
            "percent": percent(semantic_supported, semantic_total),
        },
        "overall_output_accuracy": {
            "supported_evidence_units": primary_supported,
            "total_evidence_units": primary_total,
            "percent": percent(primary_supported, primary_total),
            "formula": (
                "(live-grounded structured atoms + matching live semantic "
                "components + populated source-explicit fields) / "
                "(all structured atoms + all live components + all "
                "source-explicit fields)"
                if live_records
                else "(stored-grounded atoms + deterministic semantic checks "
                "+ populated source-explicit fields) / (all atoms + semantic "
                "checks + all source-explicit fields)"
            ),
        },
    }


def markdown_report(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# Báo cáo kiểm toán độ chính xác output crawler",
        "",
        f"- Thời điểm: `{payload['generated_at']}`",
        (
            "- Phạm vi: "
            f"{summary['scope']['selected_outputs']} output thuộc "
            f"{summary['scope']['unique_diseases']} bệnh; "
            f"chế độ `{summary['scope']['selection_mode']}`."
        ),
        (
            "- URL live kiểm tra thành công: "
            f"{summary['scope']['live_checked']}/"
            f"{summary['scope']['selected_outputs']}."
        ),
        "",
        "## Kết quả tổng hợp",
        "",
        "| Chỉ số | Kết quả | Ý nghĩa |",
        "|---|---:|---|",
        (
            "| Độ chính xác output tổng hợp | "
            f"**{summary['overall_output_accuracy']['percent']}%** | "
            "Công thức evidence-unit được ghi bên dưới |"
        ),
        (
            "| Structured grounding trên URL live | "
            f"**{summary['live_structured_grounding_precision']['percent']}%** | "
            "Giá trị disease JSON tìm thấy nguyên văn trong nguồn live |"
        ),
        (
            "| Độ trung thực semantic | "
            f"**{summary['semantic_faithfulness']['percent']}%** | "
            "Structured atoms và main/tab đúng nguồn, chưa tính field thiếu |"
        ),
        (
            "| Độ mới semantic main + 4 tab | "
            f"**{summary['live_semantic_freshness']['percent']}%** | "
            "Component hash live trùng output |"
        ),
        (
            "| Độ đầy đủ field nguồn thể hiện rõ | "
            f"**{summary['source_explicit_field_completeness']['percent']}%** | "
            "Field có nhãn/đoạn nguồn rõ và đã được populate |"
        ),
        (
            "| Toàn vẹn artifact | "
            f"**{summary['artifact_integrity']['percent']}%** | "
            "SHA-256 file trùng manifest |"
        ),
        (
            "| Đủ bộ artifact bắt buộc | "
            f"**{summary['complete_required_artifact_sets']['percent']}%** | "
            "Có raw/main/tabs/JSON/PNG |"
        ),
        (
            "| Tái tạo raw → clean → structured | "
            f"**{summary['deterministic_transform_fidelity']['percent']}%** | "
            "Kết quả tái tạo trùng output |"
        ),
        "",
        "### Công thức chính",
        "",
        f"`{summary['overall_output_accuracy']['formula']}`",
        "",
        "Không cộng điểm cho field trống mà nguồn không cung cấp. Độ đầy đủ chỉ",
        "tính các field có tín hiệu rõ trong HTML nguồn (title, paragraph hoặc",
        "nhãn bảng đã map vào schema).",
        "",
        "## Kết quả theo bệnh",
        "",
        "| Bệnh | Live | Atom đúng | Field đủ | Artifact | Thành phần thay đổi |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for record in payload["items"]:
        live = record["live"] or {}
        atom_supported = live.get(
            "supported_atoms",
            sum(atom["supported"] for atom in record["atoms"]),
        )
        atom_total = live.get("total_atoms", len(record["atoms"]))
        live_label = (
            "LỖI"
            if live.get("error")
            else "TRÙNG"
            if live.get("snapshot_match")
            else "ĐỔI"
            if live
            else "CHƯA KIỂM"
        )
        changed = (
            ", ".join(
                key
                for key, matched in live.get(
                    "component_matches", {}
                ).items()
                if not matched
            )
            or "—"
        )
        lines.append(
            "| [{title}]({url}) | {live} | {atoms} | {fields} | {artifact} | "
            "{changed} |".format(
                title=str(record["title"]).replace("|", "\\|"),
                url=record["url"],
                live=live_label,
                atoms=f"{atom_supported}/{atom_total}",
                fields=(
                    f"{len(record['populated_source_fields'])}/"
                    f"{len(record['expected_source_fields'])}"
                ),
                artifact="OK" if record["artifact_integrity"] else "LỖI",
                changed=changed,
            )
        )
    lines.extend(
        [
            "",
            "## Dẫn chứng và ngoại lệ",
            "",
        ]
    )
    exceptions = 0
    for record in payload["items"]:
        unsupported = [atom for atom in record["atoms"] if not atom["supported"]]
        live_error = (record["live"] or {}).get("error")
        missing = record["missing_source_fields"]
        if (
            not unsupported
            and not live_error
            and not missing
            and not record["missing_required_artifacts"]
        ):
            continue
        exceptions += 1
        lines.append(f"### {record['title']}")
        lines.append("")
        lines.append(f"- URL: {record['url']}")
        if live_error:
            lines.append(f"- Lỗi kiểm tra live: `{live_error}`")
        if missing:
            lines.append(f"- Field nguồn có nhưng output thiếu: `{', '.join(missing)}`")
            lines.extend(
                f"  - `{field}` ← {record['expected_field_evidence'][field]}"
                for field in missing
            )
        if record["missing_required_artifacts"]:
            lines.append(
                "- Artifact bắt buộc còn thiếu: `"
                + ", ".join(record["missing_required_artifacts"])
                + "`"
            )
        if unsupported:
            lines.append(
                "- Atom chưa tìm thấy nguyên văn trong stored source: "
                + ", ".join(
                    f"`{atom['field']}:{atom['value_hash'][:12]}`"
                    for atom in unsupported
                )
            )
        excerpt = record["evidence_excerpt"]
        if excerpt:
            lines.append(
                f"- Mẫu dẫn chứng nguồn (tối đa 15 từ): “{excerpt}”"
            )
        lines.append("")
    if exceptions == 0:
        lines.append("Không có ngoại lệ trong phạm vi kiểm toán.")
    lines.extend(
        [
            "",
            "## Khả năng tái kiểm",
            "",
            "Báo cáo JSON cùng thư mục chứa hash từng atom, checksum từng artifact,",
            "snapshot/component hash, parser/model version và kết quả live của từng",
            "URL. Không lưu username, password, cookie hoặc Gemini API key.",
            "",
        ]
    )
    return "\n".join(lines)


async def main() -> None:
    args = parse_args()
    settings = Settings()
    plugin = GenreManualsPlugin(
        base_url=str(settings.genre_manuals_base_url),
        navigation_timeout_ms=settings.browser_navigation_timeout_ms,
        selector_timeout_ms=settings.browser_selector_timeout_ms,
        detail_confidence_threshold=(
            settings.disease_detail_confidence_threshold
        ),
    )
    database = Database(settings.database_path, settings.migrations_path)
    cleaning = CleaningService(
        plugin=plugin,
        items=ItemRepository(database),
        attempts=AttemptRepository(database),
        artifacts=ArtifactStore(settings.output_root),
        extractor=ContentExtractor(minimum_chars=50),
    )
    selection_mode = (
        "all_parsed_versions"
        if args.all_versions
        else "latest_parsed_per_unique_item"
    )
    audit_items = selected_items(
        settings,
        all_versions=args.all_versions,
    )
    records: list[tuple[AuditItem, dict[str, Any]]] = []
    for index, audit_item in enumerate(audit_items, start=1):
        print(
            f"[offline {index}/{len(audit_items)}] "
            f"{audit_item.item.title_hint}",
            flush=True,
        )
        record, _, _ = offline_item_audit(
            audit_item,
            artifacts=ArtifactStore(settings.output_root),
            cleaning=cleaning,
        )
        records.append((audit_item, record))
    if args.live:
        await live_audit(
            records,
            settings=settings,
            plugin=plugin,
            cleaning=cleaning,
        )
    elif args.reuse_live is not None:
        previous = json.loads(args.reuse_live.read_text(encoding="utf-8"))
        live_by_item = {
            item["item_id"]: item.get("live")
            for item in previous.get("items", [])
        }
        for audit_item, record in records:
            record["live"] = live_by_item.get(audit_item.item.item_id)
    item_payloads = [record for _, record in records]
    live_requested = args.live or args.reuse_live is not None
    payload = {
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "methodology": {
            "selection": "latest parsed row per unique item_id",
            "cleaner_version": CLEANER_VERSION,
            "copyright_note": (
                "Only short evidence excerpts are retained; credentials and "
                "session data are excluded"
            ),
            "live_evidence_source": (
                str(args.reuse_live)
                if args.reuse_live is not None
                else "fresh_authenticated_browser_check"
                if args.live
                else None
            ),
        },
        "summary": summarize(
            item_payloads,
            live_requested,
            selection_mode=selection_mode,
        ),
        "items": item_payloads,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    json_path = args.output_dir / f"accuracy-audit-{stamp}.json"
    markdown_path = args.output_dir / f"accuracy-audit-{stamp}.md"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(markdown_report(payload), encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    print(f"JSON_REPORT={json_path}")
    print(f"MARKDOWN_REPORT={markdown_path}")


if __name__ == "__main__":
    asyncio.run(main())
