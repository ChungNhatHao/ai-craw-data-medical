const stageDefaults = [
  ["validate", "Kiểm tra yêu cầu"],
  ["authenticate", "Đăng nhập & session"],
  ["navigate", "Tìm trang bệnh"],
  ["discover", "Tìm & xác minh bệnh"],
  ["profile", "Quét cấu trúc nguồn"],
  ["fetch", "Tải dữ liệu gốc"],
  ["clean", "Làm sạch & Markdown"],
  ["parse", "Structured JSON"],
  ["coverage", "Kiểm tra độ đầy đủ"],
  ["report", "Report & output"],
];

const terminalStates = new Set(["completed", "completed_with_errors", "failed"]);
const artifactLabels = {
  "raw_html": ["Raw", "raw.html"],
  "tabs_raw": ["Tabs Raw", "tabs-raw.json"],
  "tabs": ["4 Tabs", "tabs.json"],
  "content_html": ["HTML", "content.html"],
  "markdown": ["MD", "markdown.md"],
  "disease_json": ["JSON", "disease.json"],
  "disease_draft": ["Draft", "disease-draft.json"],
  "normalization": ["Normalize", "normalization.json"],
  "coverage": ["Coverage", "coverage.json"],
  "screenshot": ["PNG", "screenshot.png"],
};

const requestedJobId = new URLSearchParams(window.location.search).get("job");
let activeJobId = sessionStorage.getItem("activeCrawlerJob");
let lastJobId = requestedJobId || sessionStorage.getItem("lastCrawlerJob");
let pollTimer = null;
let runStartedAt = null;
let discoveryMode = "automatic";

const form = document.querySelector("#runForm");
const runButton = document.querySelector("#runButton");
const formError = document.querySelector("#formError");
const stageList = document.querySelector("#stageList");
const runBadge = document.querySelector("#runBadge");
const runMeta = document.querySelector("#runMeta");
const resultsPanel = document.querySelector("#resultsPanel");
const runError = document.querySelector("#runError");

function importedDiseaseNames() {
  const values = document.querySelector("#diseaseNames").value
    .split(/\r?\n|;/)
    .map(value => value.trim())
    .filter(Boolean);
  return [...new Map(values.map(value => [value.toLocaleLowerCase(), value])).values()];
}

function updateImportedDiseaseCount() {
  const names = importedDiseaseNames();
  document.querySelector("#diseaseNameCount").textContent =
    `${names.length} tên hợp lệ`;
  updateCategoryExpansionSummary(names.length);
  return names;
}

function categoryOptionValue(selector) {
  return Number(document.querySelector(selector).value);
}

function updateCategoryExpansionSummary(rootCount = importedDiseaseNames().length) {
  const enabled = document.querySelector("#expandDiseaseCategories").checked;
  const maximum = categoryOptionValue("#categoryMaxDiseases");
  document.querySelector("#categoryExpansionSummary").textContent =
    `${rootCount} tên gốc · mở rộng menu ${enabled ? "đang bật" : "đã tắt"} · ` +
    `tối đa ${maximum} bệnh con`;
}

function setDiscoveryMode(mode) {
  discoveryMode = mode === "import" ? "import" : "automatic";
  document.querySelectorAll(".crawl-mode-tab").forEach(tab => {
    const active = tab.dataset.mode === discoveryMode;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  document.querySelector("#automaticModePanel").hidden =
    discoveryMode !== "automatic";
  document.querySelector("#importModePanel").hidden =
    discoveryMode !== "import";
  document.querySelector("#agenticOptionTitle").textContent =
    "Gemini Agentic Discovery";
  document.querySelector("#agenticOptionDescription").textContent =
    "AI chọn candidate và xác minh trang bệnh; không quyết định chế độ parsing.";
  runButton.querySelector("span").textContent = discoveryMode === "import"
    ? "Tìm và crawl danh sách bệnh"
    : "Thực thi crawler tự động";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function initialStages() {
  return stageDefaults.map(([name, label]) => ({
    name, label, state: "pending", message: "Đang chờ", current: 0, total: 0,
  }));
}

function stateLabel(state) {
  return {
    queued: "QUEUED",
    running: "RUNNING",
    completed: "COMPLETED",
    completed_with_errors: "WITH ERRORS",
    failed: "FAILED",
    pending: "PENDING",
  }[state] || state;
}

function renderStages(stages) {
  stageList.innerHTML = stages.map((stage, index) => {
    const progress = stage.state === "completed"
      ? 100
      : stage.total > 0
        ? Math.min(100, Math.round((stage.current / stage.total) * 100))
        : stage.state === "running" ? 22 : 0;
    const icon = stage.state === "completed" ? "✓"
      : stage.state === "failed" ? "!"
      : String(index + 1).padStart(2, "0");
    const time = stage.finished_at
      ? new Date(stage.finished_at).toLocaleTimeString("vi-VN", {hour: "2-digit", minute: "2-digit"})
      : stage.state === "running" ? "LIVE" : "";
    const counters = stage.category_counters || stage.counters;
    const counterLabels = counters
      ? [
          ["imported_roots_processed", "tên gốc"],
          ["categories_expanded", "danh mục"],
          ["queued_nodes", "đang chờ"],
          ["confirmed_diseases", "bệnh"],
          ["skipped_nodes", "bỏ qua"],
          ["failed_nodes", "lỗi"],
        ].filter(([key]) => Number.isFinite(Number(counters[key])))
          .map(([key, label]) => `${Number(counters[key])} ${label}`)
      : [];
    return `
      <article class="stage-row ${escapeHtml(stage.state)}">
        <span class="stage-icon">${icon}</span>
        <div class="stage-copy">
          <div class="stage-title">
            <strong>${escapeHtml(stage.label)}</strong>
            <span>${escapeHtml(stateLabel(stage.state))}</span>
          </div>
          <p class="stage-message">${escapeHtml(stage.message)}</p>
          ${counterLabels.length
            ? `<p class="stage-counters">${counterLabels.map(escapeHtml).join(" · ")}</p>`
            : ""}
          <div class="progress-track">
            <div class="progress-bar" style="width:${progress}%"></div>
          </div>
        </div>
        <span class="stage-time">${time}</span>
      </article>`;
  }).join("");
}

function setRunState(snapshot) {
  runBadge.textContent = stateLabel(snapshot.state);
  runBadge.className = `run-badge ${
    snapshot.state === "running" || snapshot.state === "queued"
      ? "running"
      : snapshot.state === "failed" ? "failed" : "completed"
  }`;
  const elapsed = runStartedAt
    ? Math.max(0, Math.round((Date.now() - runStartedAt) / 1000))
    : 0;
  runMeta.textContent = `Job ${snapshot.job_id.slice(0, 8)} · ${elapsed}s · cập nhật tự động`;
  renderStages(snapshot.stages);
  runError.hidden = snapshot.state !== "failed";
  if (snapshot.state === "failed") {
    document.querySelector("#runErrorCode").textContent = snapshot.error_code || "RUN_FAILED";
    document.querySelector("#runErrorMessage").textContent =
      snapshot.error_message || "Pipeline không thể hoàn tất.";
  }
}

async function api(url, options) {
  const response = await fetch(url, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = Array.isArray(body.detail)
      ? body.detail.map(item => item.msg).join("; ")
      : body.detail;
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return body;
}

async function checkHealth() {
  const dot = document.querySelector("#healthDot");
  const text = document.querySelector("#healthText");
  try {
    const health = await api("/api/v1/health/ready");
    dot.className = "health-dot ok";
    text.textContent = health.status === "ready" ? "Hệ thống sẵn sàng" : "Chưa sẵn sàng";
    const agentic = document.querySelector("#agenticDiscovery");
    const parsing = document.querySelector("#agenticParsing");
    const normalization = document.querySelector("#aiNormalization");
    const geminiReady = health.gemini_agentic === "ready";
    const agenticReady = geminiReady && health.agentic_discovery_enabled;
    const parsingReady = geminiReady && health.agentic_parsing_enabled;
    const normalizationReady = geminiReady && health.ai_normalization_enabled;
    agentic.disabled = !agenticReady;
    parsing.disabled = !parsingReady;
    normalization.disabled = !normalizationReady;
    const geminiReason = geminiReady
      ? ""
      : health.gemini_agentic === "disabled"
        ? "Backend chưa bật tính năng Gemini"
        : "Backend chưa cấu hình GEMINI_API_KEY";
    agentic.title = agenticReady
      ? ""
      : geminiReason || "Backend chưa bật AGENTIC_DISCOVERY_ENABLED";
    parsing.title = parsingReady
      ? ""
      : geminiReason || "Backend chưa bật AGENTIC_PARSING_ENABLED";
    normalization.title = normalizationReady
      ? ""
      : geminiReason || "Backend chưa bật AI_NORMALIZATION_ENABLED";
  } catch {
    dot.className = "health-dot error";
    text.textContent = "Không kết nối được backend";
  }
}

async function pollRun() {
  if (!activeJobId) return;
  try {
    const snapshot = await api(`/api/v1/jobs/runs/${activeJobId}`);
    setRunState(snapshot);
    if (terminalStates.has(snapshot.state)) {
      clearInterval(pollTimer);
      pollTimer = null;
      runButton.disabled = false;
      setDiscoveryMode(discoveryMode);
      if (snapshot.report_available) {
        await loadReport(activeJobId);
        lastJobId = activeJobId;
        sessionStorage.setItem("lastCrawlerJob", activeJobId);
      }
      if (snapshot.state !== "failed") sessionStorage.removeItem("activeCrawlerJob");
    }
  } catch (error) {
    clearInterval(pollTimer);
    pollTimer = null;
    try {
      await loadReport(activeJobId);
      lastJobId = activeJobId;
      sessionStorage.setItem("lastCrawlerJob", activeJobId);
      sessionStorage.removeItem("activeCrawlerJob");
      runMeta.textContent = `Đã khôi phục report job ${activeJobId.slice(0, 8)}`;
      runBadge.textContent = "REPORT";
      runBadge.className = "run-badge completed";
    } catch {
      formError.textContent = error.message;
    } finally {
      runButton.disabled = false;
      setDiscoveryMode(discoveryMode);
    }
  }
}

async function loadReport(jobId) {
  const report = await api(`/api/v1/jobs/${jobId}/report`);
  resultsPanel.hidden = false;
  document.querySelector("#totalItems").textContent = report.total_items;
  document.querySelector("#successItems").textContent = report.successful_items;
  document.querySelector("#failedItems").textContent = report.failed_items;
  document.querySelector("#newItems").textContent = report.new_items || 0;
  document.querySelector("#updatedItems").textContent = report.updated_items || 0;
  document.querySelector("#unchangedItems").textContent = report.unchanged_items || 0;
  document.querySelector("#missingFieldItems").textContent =
    report.items_with_missing_fields || 0;
  document.querySelector("#coverageStatus").textContent =
    report.coverage_complete
      ? "Đạt"
      : `Thiếu (${report.coverage_failed_items || 0})`;
  document.querySelector("#finalStatus").textContent = stateLabel(report.status);
  document.querySelector("#reportLink").href = `/api/v1/jobs/${jobId}/report`;
  document.querySelector("#discoveryLink").href =
    `/api/v1/jobs/${jobId}/artifacts/ai-discovery.json`;
  document.querySelector("#agentTraceLink").href =
    `/api/v1/jobs/${jobId}/agent-trace`;
  const importAuditLink = document.querySelector("#importAuditLink");
  importAuditLink.href =
    `/api/v1/jobs/${jobId}/artifacts/import-search.json`;
  const auditResponse = await fetch(importAuditLink.href);
  importAuditLink.hidden = !auditResponse.ok;
  if (auditResponse.ok) {
    renderSearchDecisions(await auditResponse.json());
  } else {
    renderSearchDecisions(null);
  }
  const categoryExpansionLink = document.querySelector("#categoryExpansionLink");
  categoryExpansionLink.href =
    `/api/v1/jobs/${jobId}/artifacts/category-expansion.json`;
  const categoryResponse = await fetch(categoryExpansionLink.href);
  categoryExpansionLink.hidden = !categoryResponse.ok;
  const siteProfileLink = document.querySelector("#siteProfileLink");
  siteProfileLink.href = `/api/v1/jobs/${jobId}/artifacts/site-profile.json`;
  const siteProfileResponse = await fetch(siteProfileLink.href);
  siteProfileLink.hidden = !siteProfileResponse.ok;
  const coverageReportLink = document.querySelector("#coverageReportLink");
  coverageReportLink.href =
    `/api/v1/jobs/${jobId}/artifacts/coverage-report.json`;
  const coverageResponse = await fetch(coverageReportLink.href);
  coverageReportLink.hidden = !coverageResponse.ok;

  renderCategoryWarnings(report);
  document.querySelector("#resultRows").innerHTML = renderReportRows(
    report.items,
    jobId,
  );
  resultsPanel.scrollIntoView({behavior: "smooth", block: "start"});
}

function renderSearchDecisions(audit) {
  const panel = document.querySelector("#searchDecisionPanel");
  const rows = document.querySelector("#searchDecisionRows");
  const attempts = audit?.attempts || [];
  const decisions = attempts.filter(attempt =>
    (attempt.autocomplete_suggestions || []).length
    || attempt.autocomplete_reason,
  );
  panel.hidden = decisions.length === 0;
  rows.innerHTML = decisions.map(attempt => {
    const suggestions = attempt.autocomplete_suggestions || [];
    const selectedNames = attempt.autocomplete_selected_names?.length
      ? attempt.autocomplete_selected_names
      : (
        attempt.autocomplete_selected_name
          ? [attempt.autocomplete_selected_name]
          : []
      );
    const resolvedNames = attempt.autocomplete_resolved_names || [];
    const confidence = attempt.autocomplete_confidence == null
      ? "—"
      : `${Math.round(Number(attempt.autocomplete_confidence) * 100)}%`;
    return `
      <article class="search-decision-card">
        <div class="search-decision-title">
          <div>
            <span>Tên import</span>
            <strong>${escapeHtml(attempt.disease_name)}</strong>
          </div>
          <span class="decision-source ${escapeHtml(
            attempt.autocomplete_decision_source || "none",
          )}">${escapeHtml(
            attempt.autocomplete_decision_source === "gemini"
              ? `Gemini · ${confidence}`
              : (
                attempt.autocomplete_decision_source === "all_suggestions"
                  ? "Lấy toàn bộ gợi ý"
                  : "Fallback an toàn"
              ),
          )}</span>
        </div>
        <div class="suggestion-list">
          ${suggestions.map(value => `
            <span class="${selectedNames.includes(value) ? "selected" : ""}">
              ${escapeHtml(value)}
            </span>
          `).join("") || "<span>Không có gợi ý</span>"}
        </div>
        <p>
          <strong>Kết quả chọn:</strong>
          ${escapeHtml(
            selectedNames.length
              ? selectedNames.join(" · ")
              : "Giữ nguyên tên import",
          )}
        </p>
        ${resolvedNames.length ? `
          <p>
            <strong>Tên chuẩn dùng để tìm:</strong>
            ${escapeHtml(resolvedNames.join(" · "))}
          </p>
        ` : ""}
        ${attempt.skipped_existing_count ? `
          <p>
            <strong>Đã bỏ qua:</strong>
            ${escapeHtml(String(attempt.skipped_existing_count))}
            bệnh đã hoàn tất ở lần chạy trước hoặc đã có trong job
          </p>
        ` : ""}
        <p>
          <strong>Lý do:</strong>
          ${escapeHtml(attempt.autocomplete_reason || "Không có lý do")}
        </p>
      </article>
    `;
  }).join("");
}

function normalizeProvenance(item) {
  let values = item.provenance || item.provenance_paths || [];
  if (!Array.isArray(values)) values = [values];
  if (!values.length && (item.root_query || item.menu_path)) {
    values = [{
      root_query: item.root_query,
      menu_path: item.menu_path,
      depth: item.depth,
    }];
  }
  return values.filter(Boolean).map(value => {
    const rawPath = value.menu_path || value.path || [];
    const menuPath = Array.isArray(rawPath)
      ? rawPath
      : String(rawPath).split(">").map(part => part.trim()).filter(Boolean);
    return {
      rootQuery: value.root_query || value.imported_root || "Tên import",
      menuPath,
      depth: value.depth,
    };
  });
}

function renderReportRows(items, jobId) {
  const hasProvenance = items.some(item => normalizeProvenance(item).length);
  if (!hasProvenance) {
    return items.map(item => renderItemRow(item, jobId)).join("");
  }

  const groups = new Map();
  const ungrouped = [];
  items.forEach(item => {
    const provenance = normalizeProvenance(item);
    if (!provenance.length) {
      ungrouped.push(item);
      return;
    }
    provenance.forEach(path => {
      const categoryPath = path.menuPath.slice(0, -1);
      const identity = JSON.stringify([path.rootQuery, categoryPath]);
      if (!groups.has(identity)) {
        groups.set(identity, {rootQuery: path.rootQuery, categoryPath, rows: []});
      }
      groups.get(identity).rows.push({item, path});
    });
  });

  const groupedRows = [...groups.values()].map(group => `
    <tr class="provenance-group">
      <td colspan="4">
        <strong>${escapeHtml(group.rootQuery)}</strong>
        <span>${group.categoryPath.length
          ? escapeHtml(group.categoryPath.join(" › "))
          : "Trang bệnh trực tiếp"}</span>
      </td>
    </tr>
    ${group.rows.map(({item, path}) => renderItemRow(item, jobId, path)).join("")}
  `).join("");
  const fallbackRows = ungrouped.length
    ? `
      <tr class="provenance-group ungrouped">
        <td colspan="4"><strong>Kết quả chưa có provenance</strong></td>
      </tr>
      ${ungrouped.map(item => renderItemRow(item, jobId)).join("")}
    `
    : "";
  return groupedRows + fallbackRows;
}

function renderItemRow(item, jobId, provenance = null) {
    const fieldLabels = {
      aliases: "Tên gọi khác",
      summary: "Tóm tắt",
      causes: "Nguyên nhân",
      risk_factors: "Yếu tố nguy cơ",
      symptoms: "Triệu chứng",
      diagnosis: "Chẩn đoán",
      treatment: "Điều trị",
      prevention: "Phòng ngừa",
      prognosis: "Tiên lượng",
      when_to_seek_care: "Khi nào cần chăm sóc",
    };
    const changeLabels = {
      new: "Mới",
      updated: "Có cập nhật",
      unchanged: "Đã crawl · không đổi",
    };
    const links = item.artifacts
      .filter(name => artifactLabels[name])
      .map(name => {
        const [label, file] = artifactLabels[name];
        const href = `/api/v1/jobs/${jobId}/items/${item.item_id}/artifacts/${file}`;
        return `<a href="${href}" target="_blank">${label}</a>`;
      }).join("");
    const diseaseUrl = item.artifacts.includes("disease_json")
      ? `/api/v1/jobs/${jobId}/items/${item.item_id}/artifacts/disease.json`
      : "";
    const viewButton = diseaseUrl
      ? `<button class="view-disease" type="button" data-disease-url="${diseaseUrl}">Xem nội dung</button>`
      : "";
    const evidence = item.complete_artifact_set
      ? '<span class="verified">✓ Đủ artifact</span>'
      : escapeHtml(item.last_error_code || "Chưa đầy đủ");
    const missingFields = item.missing_fields || [];
    const missingFieldNote = missingFields.length
      ? `<small class="missing-fields-warning">⚠ Không lấy được: ${
          missingFields.map(field =>
            escapeHtml(fieldLabels[field] || field)
          ).join(", ")
        }</small>`
      : (
        item.status === "parsed"
          ? '<small class="fields-complete">✓ Đủ dữ liệu các field</small>'
          : ""
      );
    const changeBadge = item.change_status
      ? `<span class="change-pill ${escapeHtml(item.change_status)}">${
          escapeHtml(changeLabels[item.change_status] || item.change_status)
        }</span>`
      : "";
    const changedNote = (item.changed_components || []).length
      ? `<small class="changed-components">Thay đổi: ${
          item.changed_components.map(escapeHtml).join(", ")
        }</small>`
      : "";
    const provenanceNote = provenance
      ? `<small class="provenance-path">${
          escapeHtml(provenance.menuPath.join(" › ") || provenance.rootQuery)
        }${
          Number.isFinite(Number(provenance.depth))
            ? ` · cấp ${Number(provenance.depth)}`
            : ""
        }</small>`
      : "";
    return `
      <tr>
        <td class="item-name">
          <strong>${escapeHtml(item.title || "Untitled item")}</strong>
          <small>${escapeHtml(item.item_id.slice(0, 12))}</small>
          ${provenanceNote}
        </td>
        <td><span class="status-pill ${escapeHtml(item.status)}">${escapeHtml(item.status)}</span></td>
        <td>${evidence}${changeBadge}${changedNote}${missingFieldNote}</td>
        <td><div class="artifact-links">${viewButton}${links || "—"}</div></td>
      </tr>`;
}

function renderCategoryWarnings(report) {
  const warningBox = document.querySelector("#categoryWarnings");
  const warnings = [
    ...(report.warnings || []),
    ...(report.items || []).flatMap(item => item.warnings || []),
  ];
  const limitWarnings = [...new Set(warnings.filter(value =>
    /category_(depth|node|disease)_limit|category.*limit/i.test(value),
  ))];
  const coverageIncomplete = report.coverage_complete !== true;
  warningBox.hidden = !coverageIncomplete && limitWarnings.length === 0;
  warningBox.innerHTML = [
    coverageIncomplete
      ? `<strong>Coverage chưa đạt — job không được coi là hoàn tất đầy đủ.</strong>
         <span>${Number(report.coverage_failed_items || 0)} item bị từ chối.</span>`
      : "",
    limitWarnings.length
      ? `<strong>Kết quả một phần do đã chạm giới hạn mở rộng menu.</strong>
         <span>${limitWarnings.map(escapeHtml).join(" · ")}</span>`
      : "",
  ].filter(Boolean).join("<br>");
}

function renderDisease(diseaseDocument) {
  const disease = diseaseDocument.disease || {};
  const source = diseaseDocument.source || {};
  const metadata = diseaseDocument.parse_metadata || {};
  const fields = [
    ["Nguyên nhân", disease.causes],
    ["Yếu tố nguy cơ", disease.risk_factors],
    ["Triệu chứng", disease.symptoms],
    ["Chẩn đoán", disease.diagnosis],
    ["Điều trị", disease.treatment],
    ["Phòng ngừa", disease.prevention],
    ["Tiên lượng", disease.prognosis],
    ["Khi nào cần chăm sóc", disease.when_to_seek_care],
  ];

  document.querySelector("#diseaseName").textContent =
    disease.name || "Bệnh chưa xác định";
  document.querySelector("#diseaseMeta").innerHTML = `
    <span>Schema ${escapeHtml(diseaseDocument.schema_version || "—")}</span>
    <span>Ngôn ngữ: ${escapeHtml(source.language || "—")}</span>
    <span>Parser: ${escapeHtml(metadata.parser_version || "—")}</span>
    <span>Hash: ${escapeHtml((source.content_hash || "").slice(0, 12))}</span>
    ${source.canonical_url
      ? `<a href="${escapeHtml(source.canonical_url)}" target="_blank" rel="noreferrer">Mở nguồn ↗</a>`
      : ""}
  `;
  document.querySelector("#diseaseAliases").innerHTML =
    (disease.aliases || []).map(alias => `<span>${escapeHtml(alias)}</span>`).join("");
  document.querySelector("#diseaseSummary").innerHTML = `
    <strong>Tóm tắt</strong>
    ${disease.summary
      ? escapeHtml(disease.summary)
      : '<span class="empty-value">Không lấy được dữ liệu cho field này.</span>'}
  `;
  document.querySelector("#diseaseFields").innerHTML = fields.map(([label, value]) => {
    const values = Array.isArray(value) ? value : value ? [value] : [];
    const content = values.length
      ? `<ul>${values.map(item => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`
      : '<p class="empty-value">Không lấy được dữ liệu cho field này</p>';
    return `<section class="disease-field"><h4>${label}</h4>${content}</section>`;
  }).join("");
  const tabs = diseaseDocument.tabs || [];
  document.querySelector("#diseaseTabs").innerHTML = tabs.length
    ? `
      <div class="disease-tabs-heading">
        <strong>Nội dung theo tab nguồn</strong>
        <span>${tabs.filter(tab => tab.available).length}/${tabs.length} tab có dữ liệu</span>
      </div>
      ${tabs.map(tab => {
        const classification = tab.classification_table;
        const classificationRows = classification?.rows || [];
        const ratingHeaders = (classification?.headers || []).filter(header =>
          header && header.toLocaleLowerCase() !== "classification"
        );
        const hierarchyTable = classificationRows.length ? `
          <div class="source-table-scroll">
            <table class="source-table classification-table">
              <thead><tr>
                <th>Cấp</th>
                <th>Cha trực tiếp</th>
                <th>Phân loại</th>
                <th>Đường dẫn đầy đủ</th>
                ${ratingHeaders.map(header => `<th>${escapeHtml(header)}</th>`).join("")}
              </tr></thead>
              <tbody>${classificationRows.map(row => `<tr>
                <td class="classification-level">${Number(row.level) + 1}</td>
                <td>${escapeHtml(row.parent_classification || "—")}</td>
                <td>
                  <span class="classification-name" style="--hierarchy-level: ${Number(row.level) || 0}">
                    ${escapeHtml(row.classification || "")}
                  </span>
                </td>
                <td class="classification-path">${(row.classification_path || [])
                  .map(value => escapeHtml(value)).join(" › ")}</td>
                ${ratingHeaders.map(header => `<td>${escapeHtml(
                  header.toLocaleLowerCase() === "code"
                    ? (row.code || "")
                    : (row.ratings?.[header] || "")
                )}</td>`).join("")}
              </tr>`).join("")}</tbody>
            </table>
          </div>` : "";
        const tables = classificationRows.length ? "" : (tab.tables || []).map(table => {
          const rows = table.rows || [];
          if (!rows.length) return "";
          return `<div class="source-table-scroll"><table class="source-table"><tbody>${
            rows.map(row => `<tr>${
              row.map(cell => `<td>${escapeHtml(cell)}</td>`).join("")
            }</tr>`).join("")
          }</tbody></table></div>`;
        }).join("");
        const relatedDetails = (tab.related_details || []).map(detail => `
          <details class="related-detail">
            <summary>
              <span>${escapeHtml(detail.label || "Nội dung chi tiết")}</span>
              <small>${detail.available
                ? `${(detail.plain_text || "").length} ký tự`
                : "Không tải được"}</small>
            </summary>
            <div class="related-detail-body">
              ${detail.url
                ? `<a href="${escapeHtml(detail.url)}" target="_blank" rel="noreferrer">Mở trang nguồn ↗</a>`
                : ""}
              ${detail.available
                ? `<p>${escapeHtml(detail.plain_text || "Trang chi tiết không có nội dung văn bản.")}</p>`
                : `<p class="empty-value">${escapeHtml((detail.warnings || []).join(" · ") || "Không có dữ liệu")}</p>`}
            </div>
          </details>`).join("");
        return `
          <details class="source-tab" ${tab.key === "info" ? "open" : ""}>
            <summary>
              <span>${escapeHtml(tab.label)}</span>
              <small>${tab.available ? `${(tab.plain_text || "").length} ký tự` : "Không có dữ liệu"}</small>
            </summary>
            <div class="source-tab-body">
              ${tab.available
                ? `<p>${escapeHtml(tab.plain_text || "Tab không có nội dung văn bản.")}</p>
                   ${hierarchyTable}
                   ${tables}
                   ${relatedDetails
                     ? `<div class="related-details">
                          <strong>Nội dung chi tiết liên quan</strong>
                          ${relatedDetails}
                        </div>`
                     : ""}`
                : `<p class="empty-value">${escapeHtml((tab.warnings || []).join(" · ") || "Không có dữ liệu")}</p>`}
            </div>
          </details>`;
      }).join("")}`
    : "";
  const warningLabels = {
    aliases: "Tên gọi khác",
    summary: "Tóm tắt",
    causes: "Nguyên nhân",
    risk_factors: "Yếu tố nguy cơ",
    symptoms: "Triệu chứng",
    diagnosis: "Chẩn đoán",
    treatment: "Điều trị",
    prevention: "Phòng ngừa",
    prognosis: "Tiên lượng",
    when_to_seek_care: "Khi nào cần chăm sóc",
  };
  const warnings = metadata.warnings || [];
  const missingFields = warnings
    .filter(value => value.startsWith("missing_field:"))
    .map(value => value.slice("missing_field:".length))
    .filter(Boolean);
  const otherWarnings = warnings.filter(
    value => !value.startsWith("missing_field:"),
  );
  document.querySelector("#diseaseWarnings").innerHTML = warnings.length
    ? `${
        missingFields.length
          ? `<strong>⚠ Các field không lấy được dữ liệu:</strong> ${
              missingFields.map(field =>
                escapeHtml(warningLabels[field] || field)
              ).join(" · ")
            }`
          : ""
      }${
        otherWarnings.length
          ? `<br><strong>Warnings khác:</strong> ${
              otherWarnings.map(escapeHtml).join(" · ")
            }`
          : ""
      }`
    : "";
  const viewer = document.querySelector("#diseaseViewer");
  viewer.hidden = false;
  viewer.scrollIntoView({behavior: "smooth", block: "start"});
}

document.querySelector("#resultRows").addEventListener("click", async event => {
  const button = event.target.closest(".view-disease");
  if (!button) return;
  button.disabled = true;
  const previous = button.textContent;
  button.textContent = "Đang tải…";
  try {
    const document = await api(button.dataset.diseaseUrl);
    renderDisease(document);
  } catch (error) {
    formError.textContent = `Không tải được nội dung bệnh: ${error.message}`;
  } finally {
    button.disabled = false;
    button.textContent = previous;
  }
});

document.querySelector("#closeDiseaseViewer").addEventListener("click", () => {
  document.querySelector("#diseaseViewer").hidden = true;
});

form.addEventListener("submit", async event => {
  event.preventDefault();
  formError.textContent = "";
  runError.hidden = true;
  resultsPanel.hidden = true;
  if (!form.reportValidity()) return;
  const diseaseNames = updateImportedDiseaseCount();
  if (discoveryMode === "import" && diseaseNames.length === 0) {
    formError.textContent = "Hãy nhập hoặc import ít nhất một tên bệnh.";
    document.querySelector("#diseaseNames").focus();
    return;
  }
  if (diseaseNames.length > 25) {
    formError.textContent = "Danh sách import hỗ trợ tối đa 25 tên bệnh.";
    document.querySelector("#diseaseNames").focus();
    return;
  }
  if (
    document.querySelector("#aiNormalization").checked
    && !document.querySelector("#agenticParsing").checked
  ) {
    formError.textContent = "AI Normalization yêu cầu bật Gemini Agentic Parsing.";
    document.querySelector("#agenticParsing").focus();
    return;
  }
  runButton.disabled = true;
  runButton.querySelector("span").textContent = "Đang khởi tạo…";
  const payload = {
    url: document.querySelector("#url").value.trim(),
    username: document.querySelector("#username").value,
    password: document.querySelector("#password").value,
    max_items: discoveryMode === "import"
      ? diseaseNames.length
      : Number(document.querySelector("#maxItems").value),
    discovery_mode: discoveryMode,
    disease_names: discoveryMode === "import" ? diseaseNames : [],
    authorization_confirmed: document.querySelector("#authorization").checked,
    agentic_discovery: document.querySelector("#agenticDiscovery").checked,
    agentic_parsing: document.querySelector("#agenticParsing").checked,
    ai_normalization: document.querySelector("#aiNormalization").checked,
    expand_disease_categories: discoveryMode === "import"
      && document.querySelector("#expandDiseaseCategories").checked,
    category_max_depth: categoryOptionValue("#categoryMaxDepth"),
    category_max_nodes: categoryOptionValue("#categoryMaxNodes"),
    category_max_diseases: categoryOptionValue("#categoryMaxDiseases"),
  };
  try {
    const started = await api("/api/v1/jobs/runs/start", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload),
    });
    document.querySelector("#password").value = "";
    activeJobId = started.job_id;
    sessionStorage.setItem("activeCrawlerJob", activeJobId);
    runStartedAt = Date.now();
    renderStages(initialStages());
    runButton.querySelector("span").textContent = "Crawler đang chạy";
    await pollRun();
    pollTimer = setInterval(pollRun, 900);
  } catch (error) {
    formError.textContent = error.message;
    runButton.disabled = false;
    setDiscoveryMode(discoveryMode);
  }
});

document.querySelectorAll(".crawl-mode-tab").forEach(tab => {
  tab.addEventListener("click", () => setDiscoveryMode(tab.dataset.mode));
});

document.querySelector("#diseaseNames").addEventListener(
  "input",
  updateImportedDiseaseCount,
);

[
  "#expandDiseaseCategories",
  "#categoryMaxDepth",
  "#categoryMaxNodes",
  "#categoryMaxDiseases",
].forEach(selector => {
  document.querySelector(selector).addEventListener(
    "input",
    () => updateCategoryExpansionSummary(),
  );
});

document.querySelector("#diseaseNamesFile").addEventListener(
  "change",
  async event => {
    const [file] = event.target.files;
    if (!file) return;
    let imported;
    if (file.name.toLocaleLowerCase().endsWith(".xlsx")) {
      try {
        const preview = await api("/api/v1/jobs/imports/xlsx/parse", {
          method: "POST",
          headers: {
            "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          },
          body: file,
        });
        imported = preview.disease_names;
      } catch (error) {
        formError.textContent = `Không đọc được XLSX: ${error.message}`;
        event.target.value = "";
        return;
      }
    } else {
      const text = await file.text();
      imported = file.name.toLocaleLowerCase().endsWith(".csv")
        ? text.split(/\r?\n/)
          .map(line => line.split(",")[0])
          .map(value => value.trim().replace(/^["']|["']$/g, ""))
          .filter(Boolean)
        : text.split(/\r?\n/).map(value => value.trim()).filter(Boolean);
    }
    if (
      imported.length
      && ["disease", "name", "disease name", "tên bệnh"].includes(
        imported[0].toLocaleLowerCase(),
      )
    ) {
      imported.shift();
    }
    document.querySelector("#diseaseNames").value = imported.join("\n");
    formError.textContent = "";
    updateImportedDiseaseCount();
  },
);

document.querySelector("#maxItems").addEventListener("input", event => {
  document.querySelector("#maxItemsValue").textContent = event.target.value;
});

document.querySelector("#togglePassword").addEventListener("click", event => {
  const password = document.querySelector("#password");
  const reveal = password.type === "password";
  password.type = reveal ? "text" : "password";
  event.currentTarget.textContent = reveal ? "Ẩn" : "Hiện";
});

renderStages(initialStages());
setDiscoveryMode("automatic");
checkHealth();
if (activeJobId) {
  runStartedAt = Date.now();
  runButton.disabled = true;
  runButton.querySelector("span").textContent = "Đang khôi phục tiến độ";
  pollRun();
  pollTimer = setInterval(pollRun, 900);
} else if (lastJobId) {
  loadReport(lastJobId).catch(() => {
    sessionStorage.removeItem("lastCrawlerJob");
  });
}
