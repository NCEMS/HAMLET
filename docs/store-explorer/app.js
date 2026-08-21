const state = { records: [], selected: null, summary: null, tableDefinitions: null };
const detail = document.querySelector("#detail");
const list = document.querySelector("#pxd-list");
const filter = document.querySelector("#pxd-filter");
const versionFilter = document.querySelector("#version-filter");
const prideFilter = document.querySelector("#pride-filter");
const overviewButton = document.querySelector("#overview-button");
const NON_FINITE_PREFIX = "__HAMLET_NON_FINITE__";

function esc(value) {
  return String(value).replace(/[&<>"]/g, character => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[character]);
}

function parseDelimited(text, delimiter = "\t") {
  const rows = [];
  let row = [];
  let cell = "";
  let quoted = false;

  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    if (quoted) {
      if (character === '"' && text[index + 1] === '"') {
        cell += '"';
        index += 1;
      } else if (character === '"') {
        quoted = false;
      } else {
        cell += character;
      }
      continue;
    }
    if (character === '"') {
      quoted = true;
    } else if (character === delimiter) {
      row.push(cell);
      cell = "";
    } else if (character === "\n" || character === "\r") {
      if (character === "\r" && text[index + 1] === "\n") index += 1;
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
    } else {
      cell += character;
    }
  }
  if (cell || row.length) {
    row.push(cell);
    rows.push(row);
  }
  return rows;
}

async function fetchText(path) {
  const response = await fetch(`data/${path}`);
  if (!response.ok) throw new Error(`Could not load ${path}`);
  return response.text();
}

function headerDefinition(tableKey, header) {
  const normalizedHeader = header.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
  const category = state.summary?.metadata_categories?.find(item => item.header === header);
  return state.tableDefinitions?.sdrf_headers?.[header]
    || state.tableDefinitions?.tables?.[tableKey]?.[header]
    || state.tableDefinitions?.tables?.[tableKey]?.[normalizedHeader]
    || state.tableDefinitions?.defaults?.[header]
    || state.tableDefinitions?.defaults?.[normalizedHeader]
    || category?.catalog_description
    || state.tableDefinitions?.defaults?.unknown
    || "";
}

function table(title, note, rows, tableKey = title) {
  if (!rows.length) return "";
  return `<section class="section"><h3>${esc(title)}</h3><p class="section-note">${esc(note)}</p>${tableContent(rows, tableKey)}</section>`;
}

function tableContent(rows, tableKey) {
  const [header, ...body] = rows;
  return `<div class="table-frame"><table><thead><tr>${header.map(cell => `<th title="${esc(headerDefinition(tableKey, cell))}">${esc(cell)}</th>`).join("")}</tr></thead><tbody>${body.map(row => `<tr>${header.map((_, index) => `<td>${esc(row[index] || "")}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
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

function jsonKey(key) {
  return key === null ? "root" : JSON.stringify(String(key));
}

function parseJsonDocument(text) {
  try {
    return JSON.parse(text);
  } catch (parseError) {
    let replacedNonFiniteToken = false;
    const compatibleText = text.replace(/([:\[,]\s*)(-Infinity|Infinity|NaN)(?=\s*[,}\]])/g, (_, prefix, token) => {
      replacedNonFiniteToken = true;
      return `${prefix}"${NON_FINITE_PREFIX}${token}"`;
    });
    if (!replacedNonFiniteToken) throw parseError;
    return JSON.parse(compatibleText, (_, value) => {
      if (typeof value === "string" && value.startsWith(NON_FINITE_PREFIX)) {
        return Number(value.slice(NON_FINITE_PREFIX.length));
      }
      return value;
    });
  }
}

function jsonTree(value, key = null, expandRoot = false, suffix = "") {
  const property = key === null
    ? ""
    : `<span class="json-key">${esc(jsonKey(key))}</span><span class="json-punctuation">: </span>`;
  if (value !== null && typeof value === "object") {
    const isArray = Array.isArray(value);
    const entries = isArray ? value.map((item, index) => [index, item]) : Object.entries(value);
    const kind = isArray ? `array (${entries.length})` : `object (${entries.length})`;
    const opening = isArray ? "[" : "{";
    const closing = isArray ? "]" : "}";
    if (!entries.length) {
      return `<div class="json-row">${property}<span class="json-value json-empty">${opening}${closing}</span><span class="json-punctuation">${suffix}</span></div>`;
    }
    return `<details class="json-node"${expandRoot ? " open" : ""}><summary>${property}<span class="json-punctuation">${opening}</span><span class="json-kind">${esc(kind)}</span></summary><div class="json-children">${entries.map(([childKey, childValue], index) => jsonTree(childValue, childKey, false, index < entries.length - 1 ? "," : "")).join("")}</div><div class="json-closing"><span class="json-punctuation">${closing}${suffix}</span></div></details>`;
  }

  const type = value === null ? "null" : typeof value;
  const nonFiniteNumber = type === "number" && !Number.isFinite(value);
  const renderedValue = nonFiniteNumber ? String(value) : JSON.stringify(value);
  return `<div class="json-row">${property}<span class="json-value json-${nonFiniteNumber ? "nonfinite" : esc(type)}">${esc(renderedValue)}</span><span class="json-punctuation">${suffix}</span></div>`;
}

async function renderJson(path, title) {
  const text = await fetchText(path);
  try {
    const document = parseJsonDocument(text);
    return `<details class="json-viewer"><summary>${esc(title)}</summary><div class="json-tree">${jsonTree(document, null, true)}</div></details>`;
  } catch (error) {
    const content = `Raw JSON document (contains non-standard JSON values)\n\n${text}`;
    return `<details class="json-viewer"><summary>${esc(title)}</summary><pre>${esc(content)}</pre></details>`;
  }
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
      rendered.push(`<div class="table-frame"><table><thead><tr>${header.map(cell => `<th title="${esc(headerDefinition("Store vs PRIDE conflict report", cell))}">${markdownInline(cell)}</th>`).join("")}</tr></thead><tbody>${body.map(row => `<tr>${header.map((_, cellIndex) => `<td>${markdownInline(row[cellIndex] || "")}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`);
      continue;
    }
    if (line.trim()) rendered.push(`<p>${markdownInline(line)}</p>`);
  }
  return rendered.join("");
}

function confidenceRowsForDisplay(rows) {
  if (!rows.length) return rows;
  const preferred = ["sdrf row", "source name", "sdrf header", "agent confidence", "judge verdict", "judge hallucination", "judge type mismatch"];
  const [header, ...body] = rows;
  const orderedHeader = [
    ...preferred.filter(column => header.includes(column)),
    ...header.filter(column => column !== "logical field" && !preferred.includes(column)),
  ];
  const indices = orderedHeader.map(column => header.indexOf(column));
  return [orderedHeader, ...body.map(row => indices.map(index => row[index] || ""))];
}

function conflictMetricMethodology() {
  return `<aside class="metric-methodology"><h4>Metric methodology</h4><p>For a comparison unit, let <code>M</code> be matched entities, <code>A</code> HAMLET-only entities, and <code>G</code> PRIDE-only entities. Precision is <code>M / (M + A)</code>; recall is <code>M / (M + G)</code>; and F1 is <code>2PR / (P + R)</code>.</p><p><strong>Micro</strong> metrics pool entity counts before applying those formulas. <strong>Macro</strong> metrics are the arithmetic mean of the contributing unit metrics, so every unit has equal weight. <strong>Mean</strong> metrics are likewise arithmetic means of the reported precision, recall, or F1 values. Empty comparisons without a defined denominator are excluded rather than treated as zero.</p></aside>`;
}

function formatNumber(value) {
  return new Intl.NumberFormat().format(value);
}

function formatFileSize(bytes) {
  if (!Number.isFinite(bytes)) return "Unknown size";
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}

function formatStatistic(value) {
  return Number.isInteger(value) ? formatNumber(value) : Number(value).toFixed(3);
}

function histogramCard(field) {
  const maximum = Math.max(...field.histogram.map(bucket => bucket.count), 1);
  const bars = field.histogram.map(bucket => {
    const height = Math.max(3, (bucket.count / maximum) * 100);
    return `<div class="histogram-bin" title="${esc(`${bucket.label}: ${bucket.count} PXDs`)}"><span class="histogram-bar" style="height:${height}%"></span><span class="histogram-label">${esc(bucket.label)}</span></div>`;
  }).join("");
  return `<article class="histogram-card"><h4>${esc(field.field)}</h4><p>${esc(headerDefinition("llm_judge_per_paper.csv", field.field))}</p><dl><div><dt>Mean</dt><dd>${esc(formatStatistic(field.mean))}</dd></div><div><dt>Range</dt><dd>${esc(`${formatStatistic(field.minimum)}-${formatStatistic(field.maximum)}`)}</dd></div><div><dt>PXDs</dt><dd>${esc(formatNumber(field.count))}</dd></div></dl><div class="histogram" aria-label="Histogram for ${esc(field.field)}">${bars}</div></article>`;
}

function renderOverview() {
  state.selected = null;
  history.replaceState(null, "", `${location.pathname}${location.search}`);
  renderCatalog();
  const summary = state.summary;
  if (!summary) {
    detail.innerHTML = `<div class="empty-state">Store summary data is unavailable.</div>`;
    return;
  }
  const versionCards = summary.sdrf_versions.map(item => `<article class="stat-card"><span>HAMLET ${esc(item.version)}</span><strong>${esc(formatNumber(item.count))}</strong><small>PXDs with final SDRFs</small></article>`).join("");
  const categories = summary.metadata_categories.map(item => [
    item.header,
    headerDefinition("SDRF", item.header),
    item.requirement || "Not specified",
    item.type || "Not specified",
    item.ontology_accession || "Not specified",
    formatNumber(item.pxd_count),
  ]);
  const categoryRows = [["SDRF header", "Definition", "Requirement", "Type", "Ontology accession", "PXDs"], ...categories];
  detail.innerHTML = `<header class="record-header overview-header"><div><p class="eyebrow">Store overview</p><h2>HAMLET record summary</h2></div><span class="availability">${esc(formatNumber(summary.total_pxds))} catalogued PXDs</span></header>${section("HAMLET SDRFs by version", "Counts include PXDs with a final HAMLET SDRF, grouped by the schema version detected in the store.", `<div class="stat-grid">${versionCards}</div>`)}${section("LLM judge distributions", `Histograms summarize ${formatNumber(summary.judge_records)} final per-paper judge records. Hover a bar to see its bin count.`, `<div class="histogram-grid">${summary.judge_fields.map(histogramCard).join("")}</div>`)}${section("Available SDRF metadata categories", "Headers observed in final HAMLET SDRFs. Definitions are sourced from the editable table-definitions.json glossary, with term metadata from the SDRF catalog.", tableContent(categoryRows, "SDRF metadata categories"))}`;
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
  const llmJudgeJsonFiles = jsonFiles.filter(path => path.includes("/judge_output/json_outputs/"));
  const sdrfJudgeJsonFiles = jsonFiles.filter(path => path.includes("/post_judge/json_outputs/"));
  const llmResponseJsonFiles = jsonFiles.filter(path => !llmJudgeJsonFiles.includes(path) && !sdrfJudgeJsonFiles.includes(path));
  const conflictFiles = record.conflict || [];
  const conflictReport = conflictFiles.find(path => path.endsWith("/conflict_report.md"));
  const conflictTables = conflictFiles.filter(path => path.endsWith(".tsv"));
  const conflictImages = conflictFiles.filter(path => path.endsWith(".png"));
  try {
    const [sdrfRows, confidenceRows, prideRows, conflictReportText] = await Promise.all([
      sdrf ? fetchText(sdrf).then(text => parseDelimited(text)) : Promise.resolve([]),
      confidence ? fetchText(confidence).then(text => parseDelimited(text)) : Promise.resolve([]),
      record.pride ? fetchText(record.pride).then(text => parseDelimited(text)) : Promise.resolve([]),
      conflictReport ? fetchText(conflictReport) : Promise.resolve(""),
    ]);
    let html = `<header class="record-header"><h2>${esc(record.pxd)}</h2><span class="availability">${record.aggregated ? "aggregate + agentic" : "agentic artifacts"}</span></header>`;
    html += table("SDRF", "HAMLET's final Sample and Data Relationship Format (SDRF): one row per annotated sample or assay relationship.", sdrfRows) || section("SDRF", "HAMLET's final Sample and Data Relationship Format (SDRF): one row per annotated sample or assay relationship.", "<p class=\"section-note\">No SDRF TSV is stored for this PXD.</p>");
    html += table("SDRF confidence", "For each SDRF field, this sidecar records the selected source, resolution rule, agent confidence, and available judge evidence.", confidenceRowsForDisplay(confidenceRows)) || "";
    html += table("PRIDE SDRF", "The SDRF supplied by PRIDE for this PXD. It is displayed beside HAMLET's SDRF to support direct review.", prideRows) || "";
    if (conflictReportText) html += section("Store vs PRIDE conflict report", "A narrative comparison of HAMLET's stored SDRF against the PRIDE SDRF. Metrics apply only after file and field matching.", `${conflictMetricMethodology()}<div class="markdown-report">${markdown(conflictReportText)}</div>`);
    const renderedConflictTables = await Promise.all(conflictTables.map(async path => ({ path, rows: parseDelimited(await fetchText(path)) })));
    if (renderedConflictTables.length) html += section("Conflict detail tables", "Per-file, per-field, and entity matching details for the Store vs PRIDE comparison. Hover a column header to read its definition.", renderedConflictTables.map(item => `<h4>${esc(item.path.split("/").pop())}</h4>${tableContent(item.rows, item.path.split("/").pop())}`).join(""));
    if (conflictImages.length) html += section("Conflict figures", "Visual summaries generated by the Store vs PRIDE conflict assessment.", `<div class="image-grid">${conflictImages.map(path => `<a href="data/${esc(path)}" target="_blank"><img src="data/${esc(path)}" alt="${esc(path.split("/").pop())}"><span class="file-path">${esc(path.split("/").pop())}</span></a>`).join("")}</div>`);
    const images = judgeFiles.filter(path => path.endsWith(".png"));
    if (images.length) html += section("SDRF judge reports", "Quality and coverage plots from the final post-judge evaluation of HAMLET's SDRF.", `<div class="image-grid">${images.map(path => `<a href="data/${esc(path)}" target="_blank"><img src="data/${esc(path)}" alt="${esc(path.split("/").pop())}"><span class="file-path">${esc(path.split("/").pop())}</span></a>`).join("")}</div>`);
    const judgeTables = await Promise.all(judgeFiles.filter(path => path.endsWith(".csv") && !path.endsWith("/llm_judge_annotation_review.csv")).map(async path => ({ path, rows: parseDelimited(await fetchText(path), ",") })));
    html += judgeTables.map(item => table(item.path.split("/").pop(), "Final post-judge output: field-level evidence and evaluation of HAMLET's completed SDRF.", item.rows, item.path.split("/").pop())).join("");
    const renderJsonGroup = async (paths, title, description) => {
      const viewers = await Promise.all(paths.map(path => renderJson(path, `store/agentic_results_files/${record.pxd}/${path.replace(`${record.pxd}/agentic/`, "")}`)));
      if (viewers.length) html += section(title, description, `<div class="files">${viewers.join("")}</div>`);
    };
    await renderJsonGroup(llmResponseJsonFiles, "LLM responses", "JSON responses from HAMLET's biological, technical, and experimental-design metadata agents, including their integrated outputs.");
    await renderJsonGroup(llmJudgeJsonFiles, "LLM judge", "JSON output from the LLM review that evaluates agent-produced metadata before SDRF finalization.");
    await renderJsonGroup(sdrfJudgeJsonFiles, "SDRF judge", "JSON output from the post-finalization SDRF review.");
    if (record.aggregated) html += section("Aggregated results", "The consolidated pipeline record combining available PRIDE, runAssessor, organism, search, and metadata outputs.", await renderJson(record.aggregated, `store/aggregated_results_files/${record.pxd}_aggregated_results.json`));
    if (record.aggregate_omission) {
      const omission = record.aggregate_omission;
      html += section("Aggregated results", `The consolidated pipeline record was not published in this static bundle because it is ${formatFileSize(omission.size_bytes)}, above the ${formatFileSize(omission.limit_bytes)} Explorer limit.`, `<p class="section-note">Source: store/aggregated_results_files/${esc(record.pxd)}_aggregated_results.json</p>`);
    }
    detail.innerHTML = html;
  } catch (error) {
    detail.innerHTML = `<div class="empty-state">${esc(error.message)}</div>`;
  }
}

function renderCatalog() {
  const term = filter.value.trim().toLowerCase();
  const selectedVersion = versionFilter.value;
  const selectedPride = prideFilter?.value || "";
  const shown = state.records.filter(record => record.pxd.toLowerCase().includes(term) && (!selectedVersion || (record.version || "Unknown") === selectedVersion) && (!selectedPride || Boolean(record.pride)));
  document.querySelector("#record-count").textContent = `${shown.length} of ${state.records.length} stored PXDs`;
  list.innerHTML = shown.map(record => `<button class="pxd-button ${record.pxd === state.selected ? "active" : ""}" data-pxd="${record.pxd}"><span>${record.pxd}</span><span class="pxd-meta"><span class="version-badge">${esc(record.version || "Unknown")}</span><span class="badge">${record.agentic.length + Number(Boolean(record.aggregated))}</span></span></button>`).join("");
  list.querySelectorAll("button").forEach(button => button.addEventListener("click", () => renderRecord(state.records.find(record => record.pxd === button.dataset.pxd))));
}

async function initialize() {
  const [response, definitionsResponse, summaryResponse] = await Promise.all([fetch("data/store-index.json"), fetch("table-definitions.json"), fetch("data/site-summary.json")]);
  if (!response.ok) {
    throw new Error(`Could not load store index (${response.status} ${response.statusText})`);
  }
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    throw new Error(`Store index is not JSON (received ${contentType || "an unknown content type"})`);
  }
  const index = await response.json();
  if (!definitionsResponse.ok) throw new Error(`Could not load table definitions (${definitionsResponse.status} ${definitionsResponse.statusText})`);
  if (!summaryResponse.ok) throw new Error(`Could not load site summary (${summaryResponse.status} ${summaryResponse.statusText})`);
  state.tableDefinitions = await definitionsResponse.json();
  state.summary = await summaryResponse.json();
  state.records = index.pxds;
  const versions = [...new Set(state.records.map(record => record.version || "Unknown"))].sort((left, right) => left.localeCompare(right, undefined, { numeric: true }));
  versionFilter.innerHTML += versions.map(version => `<option value="${esc(version)}">${esc(version)}</option>`).join("");
  filter.addEventListener("input", renderCatalog);
  versionFilter.addEventListener("change", renderCatalog);
  if (prideFilter) prideFilter.addEventListener("change", renderCatalog);
  overviewButton.addEventListener("click", renderOverview);
  renderCatalog();
  const selected = location.hash.slice(1);
  const initial = state.records.find(record => record.pxd === selected);
  if (initial) renderRecord(initial);
  else renderOverview();
}

initialize().catch(error => { detail.innerHTML = `<div class="empty-state">${esc(error.message)}</div>`; });