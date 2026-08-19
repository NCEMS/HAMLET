const state = { records: [], selected: null };
const detail = document.querySelector("#detail");
const list = document.querySelector("#pxd-list");
const filter = document.querySelector("#pxd-filter");

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
  const [header, ...body] = rows;
  return `<section class="section"><h3>${esc(title)}</h3><p class="section-note">${esc(note)}</p><div class="table-frame"><table><thead><tr>${header.map(cell => `<th>${esc(cell)}</th>`).join("")}</tr></thead><tbody>${body.map(row => `<tr>${header.map((_, index) => `<td>${esc(row[index] || "")}</td>`).join("")}</tr>`).join("")}</tbody></table></div></section>`;
}

function uniqueJudgeFiles(files) {
  const preferred = [...files].sort((left, right) => {
    return Number(right.includes("judge_output/")) - Number(left.includes("judge_output/"));
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
  try {
    const [sdrfRows, confidenceRows] = await Promise.all([
      sdrf ? fetchText(sdrf).then(text => parseDelimited(text)) : Promise.resolve([]),
      confidence ? fetchText(confidence).then(text => parseDelimited(text)) : Promise.resolve([]),
    ]);
    let html = `<header class="record-header"><h2>${esc(record.pxd)}</h2><span class="availability">${record.aggregated ? "aggregate + agentic" : "agentic artifacts"}</span></header>`;
    html += table("SDRF", "Sample and Data Relationship Format", sdrfRows) || `<section class="section"><h3>SDRF</h3><p class="section-note">No SDRF TSV is stored for this PXD.</p></section>`;
    html += table("SDRF confidence", "Field-level provenance and confidence", confidenceRows) || "";
    const images = judgeFiles.filter(path => path.endsWith(".png"));
    if (images.length) html += `<section class="section"><h3>SDRF judge reports</h3><div class="image-grid">${images.map(path => `<a href="data/${esc(path)}" target="_blank"><img src="data/${esc(path)}" alt="${esc(path.split("/").pop())}"><span class="file-path">${esc(path.split("/").pop())}</span></a>`).join("")}</div></section>`;
    const judgeTables = await Promise.all(judgeFiles.filter(path => path.endsWith(".csv")).map(async path => ({ path, rows: parseDelimited(await fetchText(path), ",") })));
    html += judgeTables.map(item => table(item.path.split("/").pop(), "LLM judge report", item.rows)).join("");
    const fileLinks = files.filter(path => !path.endsWith(".tsv") && !path.endsWith(".csv") && !path.endsWith(".png")).map(path => `<div class="file"><span class="file-path">${esc(path)}</span><a href="data/${esc(path)}" target="_blank">Open</a></div>`).join("");
    if (fileLinks) html += `<section class="section"><h3>Agentic metadata</h3><div class="files">${fileLinks}</div></section>`;
    const viewers = await Promise.all(jsonFiles.slice(0, 12).map(path => renderJson(path, `store/agentic_results_files/${record.pxd}/${path.replace(`${record.pxd}/agentic/`, "")}`)));
    if (viewers.length) html += `<section class="section"><h3>Interactive JSON</h3><div class="files">${viewers.join("")}</div></section>`;
    if (record.aggregated) html += `<section class="section"><h3>Aggregated results</h3>${await renderJson(record.aggregated, `store/aggregated_results_files/${record.pxd}_aggregated_results.json`)}</section>`;
    detail.innerHTML = html;
  } catch (error) {
    detail.innerHTML = `<div class="empty-state">${esc(error.message)}</div>`;
  }
}

function renderCatalog() {
  const term = filter.value.trim().toLowerCase();
  const shown = state.records.filter(record => record.pxd.toLowerCase().includes(term));
  list.innerHTML = shown.map(record => `<button class="pxd-button ${record.pxd === state.selected ? "active" : ""}" data-pxd="${record.pxd}"><span>${record.pxd}</span><span class="badge">${record.agentic.length + Number(Boolean(record.aggregated))}</span></button>`).join("");
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
  document.querySelector("#record-count").textContent = `${state.records.length} stored PXDs`;
  filter.addEventListener("input", renderCatalog);
  renderCatalog();
  const selected = location.hash.slice(1);
  const initial = state.records.find(record => record.pxd === selected) || state.records[0];
  if (initial) renderRecord(initial);
}

initialize().catch(error => { detail.innerHTML = `<div class="empty-state">${esc(error.message)}</div>`; });