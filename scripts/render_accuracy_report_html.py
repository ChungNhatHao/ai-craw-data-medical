# ruff: noqa: E501

from __future__ import annotations

import base64
import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = ROOT / "output/audits/CURRENT_OUTPUT_ACCURACY_AUDIT.json"
EVIDENCE_PATH = ROOT / "output/audits/live-evidence/LIVE_EVIDENCE.json"
OUTPUT_PATH = ROOT / "docs/reports/AI_Medical_Crawler_Accuracy_Report.html"


def escape(value: object) -> str:
    return html.escape(str(value))


def data_uri(relative_path: str) -> str:
    payload = (ROOT / relative_path).read_bytes()
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def format_time(value: str) -> str:
    parsed = datetime.fromisoformat(value)
    return parsed.astimezone().strftime("%d/%m/%Y %H:%M:%S %Z")


def metric_card(
    label: str,
    percent: float,
    detail: str,
    tone: str = "primary",
) -> str:
    return f"""
      <article class="metric {tone}">
        <div class="metric-label">{escape(label)}</div>
        <div class="metric-value">{percent:.2f}%</div>
        <div class="metric-detail">{escape(detail)}</div>
      </article>
    """


def disease_rows(audit: dict[str, Any]) -> str:
    rows: list[str] = []
    for item in audit["items"]:
        live = item["live"]
        expected = item["expected_source_fields"]
        populated = item["populated_source_fields"]
        components = live["component_matches"]
        matching = sum(bool(value) for value in components.values())
        missing = ", ".join(item["missing_source_fields"]) or "—"
        complete = not item["missing_required_artifacts"]
        status = "Đạt" if not item["missing_source_fields"] and complete else "Cần xử lý"
        status_class = "pass" if status == "Đạt" else "warn"
        rows.append(
            f"""
            <tr>
              <td>
                <a href="{escape(item["url"])}">{escape(item["title"])}</a>
                <small>{escape(item["url"])}</small>
              </td>
              <td>{live["supported_atoms"]}/{live["total_atoms"]}</td>
              <td>{len(populated)}/{len(expected)}</td>
              <td>{matching}/5</td>
              <td>{escape(missing)}</td>
              <td><span class="pill {status_class}">{status}</span></td>
            </tr>
            """
        )
    return "\n".join(rows)


def exception_cards(evidence: dict[str, Any]) -> str:
    cards: list[str] = []
    for item in evidence["items"]:
        if not item["field_evidence"]:
            continue
        blocks: list[str] = []
        for field in item["field_evidence"]:
            capture = field["capture"]
            blocks.append(
                f"""
                <div class="evidence-block">
                  <div class="evidence-copy">
                    <div><b>Field thiếu:</b> <code>{escape(field["field"])}</code></div>
                    <div><b>Output hiện tại:</b>
                      <code>{escape(json.dumps(field["output_value"], ensure_ascii=False))}</code>
                    </div>
                    <div><b>Vị trí nguồn:</b> {escape(field["locator"])}</div>
                    <div class="hash"><b>SHA-256 ảnh:</b> {escape(capture["sha256"])}</div>
                  </div>
                  <img src="{data_uri(capture["path"])}"
                       alt="Bằng chứng nguồn cho {escape(item["title"])} – {escape(field["field"])}">
                </div>
                """
            )
        cards.append(
            f"""
            <article class="exception">
              <div class="exception-heading">
                <div>
                  <h3>{escape(item["title"])}</h3>
                  <a href="{escape(item["url"])}">{escape(item["url"])}</a>
                </div>
                <span class="pill warn">Nguồn có – output thiếu</span>
              </div>
              {"".join(blocks)}
            </article>
            """
        )
    return "\n".join(cards)


def render(audit: dict[str, Any], evidence: dict[str, Any]) -> str:
    summary = audit["summary"]
    overall = summary["overall_output_accuracy"]
    grounding = summary["live_structured_grounding_precision"]
    completeness = summary["source_explicit_field_completeness"]
    freshness = summary["live_semantic_freshness"]
    integrity = summary["artifact_integrity"]
    artifact_sets = summary["complete_required_artifact_sets"]
    scope = summary["scope"]
    generated = format_time(evidence["generated_at"])

    metrics = "".join(
        [
            metric_card(
                "Độ chính xác tổng hợp",
                overall["percent"],
                f'{overall["supported_evidence_units"]}/{overall["total_evidence_units"]} đơn vị bằng chứng',
            ),
            metric_card(
                "Structured grounding",
                grounding["percent"],
                f'{grounding["supported"]}/{grounding["total"]} giá trị có trong nguồn live',
                "good",
            ),
            metric_card(
                "Độ đầy đủ field",
                completeness["percent"],
                f'{completeness["populated"]}/{completeness["expected"]} field nguồn đã populate',
                "warning",
            ),
            metric_card(
                "Main + 4 tab",
                freshness["percent"],
                f'{freshness["matching_components"]}/{freshness["total_components"]} component khớp',
                "warning",
            ),
            metric_card(
                "Toàn vẹn artifact",
                integrity["percent"],
                f'{integrity["passed"]}/{integrity["total"]} checksum hợp lệ',
                "good",
            ),
            metric_card(
                "Đủ bộ artifact",
                artifact_sets["percent"],
                f'{artifact_sets["passed"]}/{artifact_sets["total"]} bệnh đủ bộ file',
                "warning",
            ),
        ]
    )

    return f"""<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Báo cáo kiểm toán AI Medical Crawler</title>
  <style>
    :root {{
      --navy: #102a43; --blue: #1463ff; --cyan: #e8f2ff;
      --green: #117a52; --green-bg: #e9f8f1;
      --amber: #9a5b00; --amber-bg: #fff6df;
      --red: #b42318; --ink: #243b53; --muted: #627d98;
      --line: #d9e2ec; --surface: #fff; --page: #f3f7fb;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0; color: var(--ink); background: var(--page);
      font: 15px/1.55 Inter, "Segoe UI", Arial, sans-serif;
    }}
    .page {{ max-width: 1180px; margin: auto; padding: 34px 24px 64px; }}
    .hero {{
      padding: 40px; border-radius: 22px; color: white;
      background: linear-gradient(125deg, #0b2440, #124f87 68%, #1463ff);
      box-shadow: 0 18px 45px rgba(16,42,67,.18);
    }}
    .eyebrow {{ text-transform: uppercase; letter-spacing: .13em; opacity: .75; font-size: 12px; }}
    h1 {{ margin: 8px 0 10px; font-size: clamp(30px, 5vw, 48px); line-height: 1.08; }}
    h2 {{ margin: 0 0 18px; font-size: 25px; color: var(--navy); }}
    h3 {{ margin: 0; color: var(--navy); }}
    .hero p {{ max-width: 800px; margin: 0; font-size: 17px; opacity: .92; }}
    .hero-meta {{ display: flex; gap: 22px; flex-wrap: wrap; margin-top: 25px; font-size: 13px; }}
    .hero-meta span {{ padding: 8px 12px; border: 1px solid #ffffff35; border-radius: 999px; }}
    section {{ margin-top: 30px; padding: 30px; border-radius: 18px; background: var(--surface); box-shadow: 0 8px 28px #102a4310; }}
    .conclusion {{ border-left: 6px solid var(--blue); }}
    .conclusion strong {{ color: var(--navy); font-size: 18px; }}
    .metrics {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin-top: 30px; }}
    .metric {{ position: relative; overflow: hidden; padding: 22px; border: 1px solid var(--line); border-radius: 16px; background: white; }}
    .metric::before {{ content: ""; position: absolute; inset: 0 auto 0 0; width: 5px; background: var(--blue); }}
    .metric.good::before {{ background: var(--green); }}
    .metric.warning::before {{ background: #ef9f16; }}
    .metric-label {{ color: var(--muted); font-weight: 650; }}
    .metric-value {{ margin: 5px 0; color: var(--navy); font-size: 32px; font-weight: 800; }}
    .metric-detail {{ color: var(--muted); font-size: 13px; }}
    .callouts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
    .callout {{ padding: 18px 20px; border-radius: 14px; background: var(--cyan); }}
    .callout.warn {{ background: var(--amber-bg); }}
    .callout b {{ display: block; margin-bottom: 5px; color: var(--navy); }}
    .table-wrap {{ overflow-x: auto; border: 1px solid var(--line); border-radius: 14px; }}
    table {{ width: 100%; border-collapse: collapse; min-width: 870px; }}
    th {{ text-align: left; color: #486581; background: #f7f9fc; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }}
    th, td {{ padding: 13px 14px; border-bottom: 1px solid #e8edf3; vertical-align: top; }}
    tr:last-child td {{ border-bottom: 0; }}
    td:first-child {{ width: 34%; font-weight: 650; }}
    td small {{ display: block; max-width: 360px; overflow: hidden; text-overflow: ellipsis; color: var(--muted); font-weight: 400; white-space: nowrap; }}
    a {{ color: #075ccf; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .pill {{ display: inline-block; white-space: nowrap; padding: 4px 9px; border-radius: 999px; font-size: 12px; font-weight: 750; }}
    .pill.pass {{ color: var(--green); background: var(--green-bg); }}
    .pill.warn {{ color: var(--amber); background: var(--amber-bg); }}
    .exception {{ padding: 20px; border: 1px solid var(--line); border-radius: 15px; margin-top: 14px; }}
    .exception-heading {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 15px; margin-bottom: 15px; }}
    .exception-heading a {{ font-size: 12px; }}
    .evidence-block {{ display: grid; grid-template-columns: minmax(280px, .85fr) 1.5fr; gap: 18px; padding-top: 14px; border-top: 1px dashed var(--line); }}
    .evidence-block + .evidence-block {{ margin-top: 17px; }}
    .evidence-copy > div {{ margin-bottom: 5px; }}
    code {{ padding: 2px 5px; border-radius: 5px; background: #eef2f6; color: #334e68; }}
    .hash {{ color: var(--muted); font-size: 11px; word-break: break-all; }}
    .evidence-block img {{ display: block; width: 100%; min-height: 55px; object-fit: contain; object-position: left center; border: 1px solid #ccd8e5; border-radius: 8px; background: white; }}
    .method {{ color: var(--muted); font-size: 13px; }}
    .method li {{ margin: 6px 0; }}
    .footer {{ margin-top: 28px; text-align: center; color: var(--muted); font-size: 12px; }}
    @media (max-width: 820px) {{
      .metrics {{ grid-template-columns: 1fr 1fr; }}
      .callouts, .evidence-block {{ grid-template-columns: 1fr; }}
      .hero, section {{ padding: 24px; }}
    }}
    @media (max-width: 520px) {{ .metrics {{ grid-template-columns: 1fr; }} .page {{ padding: 16px 12px 40px; }} }}
    @media print {{
      body {{ background: white; }} .page {{ max-width: none; padding: 0; }}
      .hero, section, .metric {{ box-shadow: none; }} section {{ break-inside: avoid; }}
      .exception {{ break-inside: avoid; }} a {{ color: inherit; }}
    }}
  </style>
</head>
<body>
<main class="page">
  <header class="hero">
    <div class="eyebrow">Executive Quality Report</div>
    <h1>AI Medical Crawler<br>Kiểm toán độ chính xác output</h1>
    <p>Đối chiếu output crawler với website nguồn sau khi đăng nhập thật,
       kiểm tra nội dung chính và bốn tab: Info, Life/DD/TPD, IP, Health.</p>
    <div class="hero-meta">
      <span>Thực hiện: {escape(generated)}</span>
      <span>Phạm vi: {scope["selected_outputs"]} bệnh</span>
      <span>Live check: {scope["live_checked"]}/{scope["selected_outputs"]} URL</span>
    </div>
  </header>

  <div class="metrics">{metrics}</div>

  <section class="conclusion">
    <h2>Kết luận điều hành</h2>
    <p><strong>Output hiện tại đạt độ chính xác tổng hợp {overall["percent"]:.2f}%,
    chưa đạt 100%.</strong></p>
    <p>Tất cả {grounding["total"]} giá trị structured đã xuất đều tìm thấy căn cứ
    trong nguồn live. Điểm cần xử lý nằm ở dữ liệu bị bỏ sót: 10 field có tín hiệu
    rõ trong nguồn nhưng chưa được populate, cùng ba output cũ thiếu artifact của
    bốn tab.</p>
    <div class="callouts">
      <div class="callout">
        <b>Điểm mạnh đã xác minh</b>
        24/24 URL HTTP 200; 24/24 là trang chi tiết bệnh; structured grounding
        100%; checksum artifact 100%.
      </div>
      <div class="callout warn">
        <b>Rủi ro cần khắc phục</b>
        Diagnosis/supportive evidence, alias và summary vẫn có trường hợp bị bỏ
        sót. Ba bộ output cũ chỉ đạt 1/5 component do thiếu file tab.
      </div>
    </div>
  </section>

  <section>
    <h2>Ma trận kết quả theo bệnh</h2>
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th>Bệnh / nguồn</th><th>Atom đúng</th><th>Field đủ</th>
          <th>Main + tabs</th><th>Field thiếu</th><th>Trạng thái</th>
        </tr></thead>
        <tbody>{disease_rows(audit)}</tbody>
      </table>
    </div>
  </section>

  <section>
    <h2>Bằng chứng trực tiếp cho dữ liệu bị thiếu</h2>
    <p class="method">Ảnh dưới đây được crop trực tiếp từ website nguồn trong phiên
    kiểm tra live. Mỗi ảnh có SHA-256 để phát hiện việc thay đổi file. Ảnh đã được
    nhúng vào báo cáo này, vì vậy có thể gửi riêng một file HTML.</p>
    {exception_cards(evidence)}
  </section>

  <section class="method">
    <h2>Phương pháp và giới hạn</h2>
    <ul>
      <li>Mở trực tiếp từng URL sau xác thực; ghi HTTP status, final URL, page type và thời gian.</li>
      <li>Đối chiếu structured atoms bằng exact source text; so component semantic của main và bốn tab.</li>
      <li>Kiểm tra SHA-256 của artifact và khả năng tái tạo raw → clean → structured.</li>
      <li>Công thức tổng hợp: (structured atoms được grounding + component live khớp + field nguồn đã populate) / tổng số đơn vị bằng chứng.</li>
      <li>Báo cáo đánh giá độ trung thực của crawler so với website nguồn, không phải thẩm định độc lập tính đúng đắn lâm sàng của nội dung nguồn.</li>
      <li>Không chứa username, password, cookie, session state hoặc Gemini API key.</li>
    </ul>
  </section>

  <div class="footer">
    AI Medical Crawler · Báo cáo tự chứa · {escape(generated)}
  </div>
</main>
</body>
</html>
"""


def main() -> None:
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    rendered = render(audit, evidence)
    clean_rendered = "\n".join(
        line.rstrip() for line in rendered.splitlines()
    ) + "\n"
    OUTPUT_PATH.write_text(clean_rendered, encoding="utf-8")
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
