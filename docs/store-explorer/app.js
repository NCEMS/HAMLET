const state = { records: [], selected: null };
const detail = document.querySelector("#detail");
const list = document.querySelector("#pxd-list");
const filter = document.querySelector("#pxd-filter");
const versionFilter = document.querySelector("#version-filter");

function esc(value) {
  return String(value).replace(/[&<>"]/g, character => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[character]);
}

function parseDelimited(text, delimiter = "\t") {
  return text.trimEnd().split(/\r?\n/).map(line => line.split(delimiter));
}

async function fetchText(path) {
  const response = await fetch(`data/${path}`);
  if (!response.ok) throw new Error(`Could not load ${path}`);
  return response.text();
}

function table(title, note, rows) {
  if (!rows.length) return "";
  return `<section class="section"><h3>${esc(title)}</h3><p class="section-note">${esc(note)}</p>${tableContent(rows)}</section>`;
}

function tableContent(rows) {
  const [header, ...body] = rows;
  return `<div class="table-frame"><table><thead><tr>${header.map(cell => `<th>${esc(cell)}</th>`).join("")}</tr></thead><tbody>${body.map(row => `<tr>${header.map((_, index) => `<td>${esc(row[index] || "")}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}

function uniqueJudgeFiles(files) {
  const preferred = [...files].sort((left, right) => {
    return Number(right.includes("post_judge/")) - Number(left.includes("post_judge/"));
  });
  const seen = new Set();
  return preferred.filter(path => {
    const filename = path.split("/").pop();
    if (seen.has(filename)) return false;
    seen.add(filename);
    return true;
  });
}

async function renderJson(path, title) {
  const text = await fetchText(path);
  let content = text;
  try {
    content = JSON.stringify(JSON.parse(text), null, 2);
  } catch (error) {
    content = `Raw JSON document (contains non-standard JSON values)\n\n${text}`;
  }
  return `<details class="json-viewer"><summary>${esc(title)}</summary><pre>${esc(content)}</pre></details>`;
}

function section(title, note, content) {
  return `<section class="section"><h3>${esc(title)}</h3><p class="section-note">${esc(note)}</p>${content}</section>`;
}

function markdownInline(text) {
  return esc(text)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`(.+?)`/g, "<code>$1</code>");
}

function markdownCells(line) {
  return line.trim().replace(/^\||\|$/g, "").split("|").map(cell => cell.trim());
}

function markdown(text) {
  const lines = text.trim().split(/\r?\n/);
  const rendered = [];
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const heading = line.match(/^#{1,3}\s+(.+)$/);
    if (heading) {
      rendered.push(`<h4>${markdownInline(heading[1])}</h4>`);
      continue;
    }
    if (line.includes("|") && /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(lines[index + 1] || "")) {
      const header = markdownCells(line);
      const body = [];
      index += 2;
      while (index < lines.length && lines[index].includes("|")) {
        body.push(markdownCells(lines[index]));
        index += 1;
      }
      index -= 1;
      rendered.push(`<div class="table-frame"><table><thead><tr>${header.map(cell => `<th>${markdownInline(cell)}</th>`).join("")}</tr></thead><tbody>${body.map(row => `<tr>${header.map((_, cellIndex) => `<td>${markdownInline(row[cellIndex] || "")}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`);
      continue;
    }
    if (line.trim()) rendered.push(`<p>${markdownInline(line)}</p>`);
  }
  return rendered.join("");
}

function conflictSummary(summary) {
  const categories = Object.entries(summary.categories || {});
  if (!categories.length) return "";
  const rows = [["Category", "Matched entities", "Precision", "Recall", "F1"], ...categories.map(([name, values]) => [
    name,
    String(values.matched_entities ?? ""),
    Number.isFinite(values.micro_precision) ? values.micro_precision.toFixed(3) : "NA",
    Number.isFinite(values.micro_recall) ? values.micro_recall.toFixed(3) : "NA",
    Number.isFinite(values.micro_f1) ? values.micro_f1.toFixed(3) : "NA",
  ])];
  return table("Conflict summary", "Agreement metrics compare HAMLET's stored SDRF with the PRIDE-provided SDRF after matching files and canonical SDRF fields.", rows);
}

async function renderRecord(record) {
  state.selected = record.pxd;
  location.hash = record.pxd;
  renderCatalog();
  detail.innerHTML = `<div class="empty-state">Loading ${esc(record.pxd)}...</div>`;
  const files = record.agentic || [];
  const sdrf = files.find(path => path.endsWith(`/${record.pxd}.sdrf.tsv`));
  const confidence = files.find(path => path.endsWith(`/${record.pxd}.confidence.sdrf.tsv`));
  const judgeFiles = uniqueJudgeFiles(files.filter(path => path.includes("judge_output/") || path.includes("post_judge/")));
  const jsonFiles = files.filter(path => path.endsWith(".json"));
  const conflictFiles = record.conflict || [];
  const conflictReport = conflictFiles.find(path => path.endsWith("/conflict_report.md"));
  const conflictSummaryPath = conflictFiles.find(path => path.endsWith("/conflict_summary.json"));
  const conflictTables = conflictFiles.filter(path => path.endsWith(".tsv"));
  const conflictImages = conflictFiles.filter(path => path.endsWith(".png"));
  try {
    const [sdrfRows, confidenceRows, prideRows, conflictReportText, conflictSummaryDocument] = await Promise.all([
      sdrf ? fetchText(sdrf).then(text => parseDelimited(text)) : Promise.resolve([]),
      confidence ? fetchText(confidence).then(text => parseDelimited(text)) : Promise.resolve([]),
      record.pride ? fetchText(record.pride).then(text => parseDelimited(text)) : Promise.resolve([]),
      conflictReport ? fetchText(conflictReport) : Promise.resolve(""),
      conflictSummaryPath ? fetchText(conflictSummaryPath).then(JSON.parse) : Promise.resolve(null),
    ]);
    let html = `<header class="record-header"><h2>${esc(record.pxd)}</h2><span class="availability">${record.aggregated ? "aggregate + agentic" : "agentic artifacts"}</span></header>`;
    html += table("SDRF", "HAMLET's final Sample and Data Relationship Format (SDRF): one row per annotated sample or assay relationship.", sdrfRows) || section("SDRF", "HAMLET's final Sample and Data Relationship Format (SDRF): one row per annotated sample or assay relationship.", "<p class=\"section-note\">No SDRF TSV is stored for this PXD.</p>");
    html += table("SDRF confidence", "For each SDRF field, this sidecar records the selected source, resolution rule, agent confidence, and available judge evidence.", confidenceRows) || "";
    html += table("PRIDE SDRF", "The SDRF supplied by PRIDE for this PXD. It is displayed beside HAMLET's SDRF to support direct review.", prideRows) || "";
    if (conflictReportText) html += section("Store vs PRIDE conflict report", "A narrative comparison of HAMLET's stored SDRF against the PRIDE SDRF. Metrics apply only after file and field matching.", `<div class="markdown-report">${markdown(conflictReportText)}</div>`);
    if (conflictSummaryDocument) html += conflictSummary(conflictSummaryDocument);
    const renderedConflictTables = await Promise.all(conflictTables.map(async path => ({ path, rows: parseDelimited(await fetchText(path)) })));
    if (renderedConflictTables.length) html += section("Conflict detail tables", "Per-file, per-field, and entity matching details for the Store vs PRIDE comparison.", renderedConflictTables.map(item => `<h4>${esc(item.path.split("/").pop())}</h4>${tableContent(item.rows)}`).join(""));
    if (conflictImages.length) html += section("Conflict figures", "Visual summaries generated by the Store vs PRIDE conflict assessment.", `<div class="image-grid">${conflictImages.map(path => `<a href="data/${esc(path)}" target="_blank"><img src="data/${esc(path)}" alt="${esc(path.split("/").pop())}"><span class="file-path">${esc(path.split("/").pop())}</span></a>`).join("")}</div>`);
    const images = judgeFiles.filter(path => path.endsWith(".png"));
    if (images.length) html += section("SDRF judge reports", "Quality and coverage plots from the final post-judge evaluation of HAMLET's SDRF.", `<div class="image-grid">${images.map(path => `<a href="data/${esc(path)}" target="_blank"><img src="data/${esc(path)}" alt="${esc(path.split("/").pop())}"><span class="file-path">${esc(path.split("/").pop())}</span></a>`).join("")}</div>`);
    const judgeTables = await Promise.all(judgeFiles.filter(path => path.endsWith(".csv")).map(async path => ({ path, rows: parseDelimited(await fetchText(path), ",") })));
    html += judgeTables.map(item => table(item.path.split("/").pop(), "Final post-judge output: field-level evidence and evaluation of HAMLET's completed SDRF.", item.rows)).join("");
    const viewers = await Promise.all(jsonFiles.slice(0, 12).map(path => renderJson(path, `store/agentic_results_files/${record.pxd}/${path.replace(`${record.pxd}/agentic/`, "")}`)));
    if (viewers.length) html += section("Agentic metadata", "Expandable JSON documents produced by HAMLET's metadata agents and final evaluation stages.", `<div class="files">${viewers.join("")}</div>`);
    if (record.aggregated) html += section("Aggregated results", "The consolidated pipeline record combining available PRIDE, runAssessor, organism, search, and metadata outputs.", await renderJson(record.aggregated, `store/aggregated_results_files/${record.pxd}_aggregated_results.json`));
    detail.innerHTML = html;
  } catch (error) {
    detail.innerHTML = `<div class="empty-state">${esc(error.message)}</div>`;
  }
}

function renderCatalog() {
  const term = filter.value.trim().toLowerCase();
  const selectedVersion = versionFilter.value;
  const shown = state.records.filter(record => record.pxd.toLowerCase().includes(term) && (!selectedVersion || (record.version || "Unknown") === selectedVersion));
  document.querySelector("#record-count").textContent = `${shown.length} of ${state.records.length} stored PXDs`;
  list.innerHTML = shown.map(record => `<button class="pxd-button ${record.pxd === state.selected ? "active" : ""}" data-pxd="${record.pxd}"><span>${record.pxd}</span><span class="pxd-meta"><span class="version-badge">${esc(record.version || "Unknown")}</span><span class="badge">${record.agentic.length + Number(Boolean(record.aggregated))}</span></span></button>`).join("");
  list.querySelectorAll("button").forEach(button => button.addEventListener("click", () => renderRecord(state.records.find(record => record.pxd === button.dataset.pxd))));
}

async function initialize() {
  const response = await fetch("data/store-index.json");
  if (!response.ok) {
    throw new Error(`Could not load store index (${response.status} ${response.statusText})`);
  }
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    throw new Error(`Store index is not JSON (received ${contentType || "an unknown content type"})`);
  }
  const index = await response.json();
  state.records = index.pxds;
  const versions = [...new Set(state.records.map(record => record.version || "Unknown"))].sort((left, right) => left.localeCompare(right, undefined, { numeric: true }));
  versionFilter.innerHTML += versions.map(version => `<option value="${esc(version)}">${esc(version)}</option>`).join("");
  filter.addEventListener("input", renderCatalog);
  versionFilter.addEventListener("change", renderCatalog);
  renderCatalog();
  const selected = location.hash.slice(1);
  const initial = state.records.find(record => record.pxd === selected) || state.records[0];
  if (initial) renderRecord(initial);
}

initialize().catch(error => { detail.innerHTML = `<div class="empty-state">${esc(error.message)}</div>`; });