import argparse
import hashlib
import html
import json
import re
import shutil
from pathlib import Path
from typing import Any

DISEASE_FIELDS = (
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
FIELD_LABELS = {
    "aliases": "Aliases",
    "summary": "Summary",
    "causes": "Causes",
    "risk_factors": "Risk factors",
    "symptoms": "Symptoms",
    "diagnosis": "Diagnosis",
    "treatment": "Treatment",
    "prevention": "Prevention",
    "prognosis": "Prognosis",
    "when_to_seek_care": "When to seek care",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export the five most complete parsed disease documents."
    )
    parser.add_argument("--job-id")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("output"),
    )
    parser.add_argument(
        "--destination",
        type=Path,
        default=Path("docs/reports/top-5-complete-diseases"),
    )
    return parser.parse_args()


def latest_job(output_root: Path) -> Path:
    reports = tuple((output_root / "jobs").glob("*/report.json"))
    if not reports:
        raise FileNotFoundError("No job report was found")
    return max(reports, key=lambda value: value.stat().st_mtime).parent


def has_value(value: Any) -> bool:
    return value not in (None, "", [], {})


def content_chars(value: Any) -> int:
    if isinstance(value, list):
        return sum(len(str(item)) for item in value)
    return len(str(value or ""))


def slugify(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return value or "disease"


def render_value(value: Any) -> str:
    if isinstance(value, list):
        if not value:
            return '<p class="missing">Not provided by source</p>'
        return "<ul>" + "".join(
            f"<li>{html.escape(str(item))}</li>" for item in value
        ) + "</ul>"
    if value in (None, ""):
        return '<p class="missing">Not provided by source</p>'
    return f"<p>{html.escape(str(value))}</p>"


def render_html(
    *,
    job_id: str,
    generated_at: str,
    selected: list[dict[str, Any]],
) -> str:
    cards: list[str] = []
    rows: list[str] = []
    for index, entry in enumerate(selected, start=1):
        document = entry["document"]
        disease = document["disease"]
        source = document["source"]
        missing = entry["missing_fields"]
        rows.append(
            "<tr>"
            f"<td>{index}</td>"
            f"<td><a href=\"#disease-{index}\">{html.escape(disease['name'])}</a></td>"
            f"<td>{entry['filled_count']}/{len(DISEASE_FIELDS)}</td>"
            f"<td>{html.escape(', '.join(missing) or 'None')}</td>"
            f"<td><a href=\"{html.escape(entry['json_name'])}\">JSON</a></td>"
            "</tr>"
        )
        fields = "".join(
            '<section class="field">'
            f"<h3>{html.escape(FIELD_LABELS[field])}</h3>"
            f"{render_value(disease.get(field))}"
            "</section>"
            for field in DISEASE_FIELDS
        )
        tabs = document.get("tabs", [])
        available_tabs = sum(bool(tab.get("available")) for tab in tabs)
        cards.append(
            f'<article class="disease" id="disease-{index}">'
            '<div class="disease-head">'
            "<div>"
            f'<span class="rank">#{index} · {entry["filled_count"]}/'
            f'{len(DISEASE_FIELDS)} fields</span>'
            f"<h2>{html.escape(disease['name'])}</h2>"
            f'<a href="{html.escape(str(source["canonical_url"]))}" '
            'target="_blank" rel="noreferrer">'
            "Open source page ↗</a>"
            "</div>"
            f'<a class="json-link" href="{html.escape(entry["json_name"])}">Raw disease JSON</a>'
            "</div>"
            '<div class="meta">'
            f"<span>Parser: {html.escape(document['parse_metadata']['parser_version'])}</span>"
            f"<span>Method: {html.escape(document['parse_metadata']['method'])}</span>"
            f"<span>Tabs: {available_tabs}/{len(tabs)} available</span>"
            f"<span>Missing: {html.escape(', '.join(missing) or 'none')}</span>"
            "</div>"
            f'<div class="fields">{fields}</div>'
            "</article>"
        )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Top 5 Most Complete Disease Results</title>
  <style>
    :root {{ --ink:#17324d; --muted:#62788d; --line:#dce5ed;
      --blue:#1769e0; --page:#f4f7fa; --warn:#9a5d16; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; color:var(--ink); background:var(--page);
      font:15px/1.55 Inter,Segoe UI,Arial,sans-serif; }}
    main {{ max-width:1180px; margin:auto; padding:32px 22px 60px; }}
    .hero {{ padding:34px; color:white; border-radius:20px;
      background:linear-gradient(125deg,#102f4c,#1769e0); }}
    .hero h1 {{ margin:5px 0 10px; font-size:clamp(30px,5vw,48px); }}
    .hero p {{ max-width:850px; margin:0; opacity:.9; }}
    .meta {{ display:flex; flex-wrap:wrap; gap:8px; margin:14px 0 20px; }}
    .meta span,.rank {{ padding:5px 9px; border-radius:999px;
      color:#31516d; background:#edf3f8; font-size:12px; }}
    .summary,.disease {{ margin-top:24px; padding:26px; background:white;
      border:1px solid var(--line); border-radius:17px; }}
    .table-wrap {{ overflow:auto; }}
    table {{ width:100%; border-collapse:collapse; min-width:700px; }}
    th,td {{ padding:11px 12px; text-align:left;
      border-bottom:1px solid var(--line); vertical-align:top; }}
    th {{ color:var(--muted); font-size:12px; text-transform:uppercase; }}
    a {{ color:var(--blue); text-decoration:none; }}
    a:hover {{ text-decoration:underline; }}
    .disease-head {{ display:flex; justify-content:space-between;
      align-items:flex-start; gap:20px; }}
    .disease h2 {{ margin:8px 0 3px; font-size:28px; }}
    .json-link {{ padding:8px 11px; border:1px solid #bad1ed;
      border-radius:9px; white-space:nowrap; }}
    .fields {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr));
      gap:12px; }}
    .field {{ padding:16px; border:1px solid var(--line);
      border-radius:12px; background:#fbfcfd; }}
    .field h3 {{ margin:0 0 8px; color:#27506f; font-size:13px;
      text-transform:uppercase; letter-spacing:.04em; }}
    .field p,.field ul {{ margin:0; }}
    .field ul {{ padding-left:19px; }}
    .field li + li {{ margin-top:6px; }}
    .missing {{ color:var(--warn); font-style:italic; }}
    footer {{ margin-top:28px; color:var(--muted); text-align:center;
      font-size:12px; }}
    @media(max-width:720px) {{
      .fields {{ grid-template-columns:1fr; }}
      .disease-head {{ display:block; }}
      .json-link {{ display:inline-block; margin-top:12px; }}
    }}
  </style>
</head>
<body>
<main>
  <header class="hero">
    <span>AI MEDICAL CRAWLER · EXPORT</span>
    <h1>Top 5 Most Complete Disease Results</h1>
    <p>Ranked by populated structured fields, then by structured content
      length. Values are grounded in the crawled source; empty fields are
      retained and clearly identified.</p>
  </header>
  <section class="summary">
    <h2>Selection summary</h2>
    <p><strong>Job:</strong> {html.escape(job_id)}<br>
      <strong>Report generated:</strong> {html.escape(generated_at)}</p>
    <div class="table-wrap"><table>
      <thead><tr><th>Rank</th><th>Disease</th><th>Filled</th>
        <th>Missing fields</th><th>Artifact</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table></div>
  </section>
  {''.join(cards)}
  <footer>Generated from authenticated crawler artifacts. Not medical advice.</footer>
</main>
</body>
</html>
"""


def main() -> None:
    args = parse_args()
    job_dir = (
        args.output_root / "jobs" / args.job_id
        if args.job_id
        else latest_job(args.output_root)
    )
    report_path = job_dir / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    ranked: list[dict[str, Any]] = []
    for item in report["items"]:
        if item["status"] != "parsed":
            continue
        document_path = args.output_root / item["artifact_dir"] / "disease.json"
        if not document_path.exists():
            continue
        document = json.loads(document_path.read_text(encoding="utf-8"))
        disease = document["disease"]
        filled_count = sum(
            has_value(disease.get(field)) for field in DISEASE_FIELDS
        )
        ranked.append(
            {
                "item": item,
                "document": document,
                "document_path": document_path,
                "filled_count": filled_count,
                "content_chars": sum(
                    content_chars(disease.get(field))
                    for field in DISEASE_FIELDS
                ),
                "missing_fields": [
                    field
                    for field in DISEASE_FIELDS
                    if not has_value(disease.get(field))
                ],
            }
        )
    selected = sorted(
        ranked,
        key=lambda value: (
            value["filled_count"],
            value["content_chars"],
            value["document"]["disease"]["name"].casefold(),
        ),
        reverse=True,
    )[:5]
    if len(selected) < 5:
        raise RuntimeError("Fewer than five parsed disease documents are available")

    args.destination.mkdir(parents=True, exist_ok=True)
    for index, entry in enumerate(selected, start=1):
        name = entry["document"]["disease"]["name"]
        json_name = f"{index:02d}-{slugify(name)}.json"
        shutil.copyfile(entry["document_path"], args.destination / json_name)
        entry["json_name"] = json_name

    selection = {
        "schema_version": "1.0",
        "source_job_id": report["job_id"],
        "source_report_generated_at": report["generated_at"],
        "ranking": "populated disease fields descending, then content length descending",
        "field_count": len(DISEASE_FIELDS),
        "items": [
            {
                "rank": index,
                "name": entry["document"]["disease"]["name"],
                "filled_field_count": entry["filled_count"],
                "missing_fields": entry["missing_fields"],
                "canonical_url": entry["document"]["source"]["canonical_url"],
                "json_file": entry["json_name"],
                "sha256": hashlib.sha256(
                    (args.destination / entry["json_name"]).read_bytes()
                ).hexdigest(),
            }
            for index, entry in enumerate(selected, start=1)
        ],
    }
    (args.destination / "selection.json").write_text(
        json.dumps(selection, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (args.destination / "index.html").write_text(
        render_html(
            job_id=report["job_id"],
            generated_at=report["generated_at"],
            selected=selected,
        ),
        encoding="utf-8",
    )
    readme_rows = "\n".join(
        f"| {index} | {entry['document']['disease']['name']} | "
        f"{entry['filled_count']}/{len(DISEASE_FIELDS)} | "
        f"{', '.join(entry['missing_fields']) or 'None'} | "
        f"[JSON]({entry['json_name']}) |"
        for index, entry in enumerate(selected, start=1)
    )
    (args.destination / "README.md").write_text(
        "# Top 5 Most Complete Disease Results\n\n"
        f"Source job: `{report['job_id']}`<br>\n"
        f"Source report generated at: `{report['generated_at']}`\n\n"
        "Ranking: populated structured fields descending, then structured "
        "content length descending.\n\n"
        "| Rank | Disease | Filled fields | Missing fields | Raw result |\n"
        "|---:|---|---:|---|---|\n"
        f"{readme_rows}\n\n"
        "Open [index.html](index.html) for the human-readable report. "
        "Checksums and selection metadata are available in "
        "[selection.json](selection.json).\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
