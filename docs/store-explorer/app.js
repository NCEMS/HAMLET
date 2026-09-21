const state = {
  records: [],
  selected: null,
  summary: null,
  qcSummary: null,
  tableDefinitions: null,
  qcTab: "version",
  qcVersion: null,
  qcMetric: "judge_accuracy",
  qcDeltaMode: "relative_delta",
  qcComparisonId: null,
  qcBaselineVersion: null,
  qcCandidateVersion: null,
  versionJudgeCache: {},
  versionMetadataCache: {},
};
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

async function fetchOptionalJson(path) {
  const response = await fetch(`data/${path}`);
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`Could not load ${path}`);
  return response.json();
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
  return `<article class="histogram-card"><h4>${esc(field.field)}</h4><p>${esc(headerDefinition("llm_judge_per_paper.csv", field.field))}</p><dl><div><dt>Mean</dt><dd>${esc(formatStatistic(field.mean))}</dd></div><div><dt>Range</dt><dd>${esc(`${formatStatistic(field.minimum)}-${formatStatistic(field.maximum)}`)}</dd></div><div><dt>PXDs</dt><dd>${esc(formatNumber(field.count))}</dd></div></dl><p class="section-note">Fixed bins: ${esc(`${formatStatistic(field.histogramMinimum)}-${formatStatistic(field.histogramMaximum)}`)}</p><div class="histogram" aria-label="Histogram for ${esc(field.field)}">${bars}</div></article>`;
}

function sortedVersions() {
  return [...new Set([
    ...state.records.map(record => record.version || "Unknown"),
    ...(state.summary?.version_judges || []).map(record => record.version),
  ])]
    .sort((left, right) => left.localeCompare(right, undefined, { numeric: true }));
}

function metricPlotId(metric) {
  const slug = String(metric).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  return `qc-version-metric-${slug}`;
}

function selectDefaultQcVersion() {
  if (state.qcVersion) return;
  const versions = sortedVersions();
  const known = versions.filter(version => version !== "Unknown");
  state.qcVersion = known[known.length - 1] || versions[0] || null;
}

function metricHistogramBounds(judgeType, metric) {
  const values = [];
  for (const versionJudge of state.summary?.version_judges || []) {
    if (versionJudge.judge_type !== judgeType) continue;
    for (const record of versionJudge.records || []) {
      const value = record.metrics?.[metric];
      if (Number.isFinite(value)) values.push(value);
    }
  }
  return values.length ? { minimum: Math.min(...values), maximum: Math.max(...values) } : null;
}

function buildHistogram(values, bins = 10, bounds = null) {
  if (!values.length) return [];
  const minimum = bounds?.minimum ?? Math.min(...values);
  const maximum = bounds?.maximum ?? Math.max(...values);
  const span = maximum - minimum;
  const step = span === 0 ? 1 : span / bins;
  const counts = new Array(bins).fill(0);
  for (const value of values) {
    let index = span === 0 ? 0 : Math.floor((value - minimum) / step);
    if (index < 0) index = 0;
    if (index >= bins) index = bins - 1;
    counts[index] += 1;
  }
  return counts.map((count, index) => {
    const lower = span === 0 ? minimum : minimum + (index * step);
    const upper = span === 0 ? maximum : (index === bins - 1 ? maximum : minimum + ((index + 1) * step));
    return {
      label: `${lower.toFixed(2)}-${upper.toFixed(2)}`,
      count,
    };
  });
}

function firstNonEmptyDataRow(rows) {
  for (let index = 1; index < rows.length; index += 1) {
    if (rows[index].some(cell => String(cell || "").trim() !== "")) return rows[index];
  }
  return null;
}

async function loadVersionJudgeMetrics(version) {
  const cached = state.versionJudgeCache[version];
  if (cached?.data) return cached.data;
  if (cached?.promise) return cached.promise;
  const promise = (async () => {
    const versionJudge = (state.summary?.version_judges || []).find(item => item.version === version);
    const records = versionJudge?.records || [];
    const metrics = versionJudge?.available_metrics || [];
    const metricPoints = Object.fromEntries(metrics.map(metric => [metric, []]));
    for (const record of records) {
      for (const metric of metrics) {
        const value = record.metrics?.[metric];
        if (Number.isFinite(value)) metricPoints[metric].push({ pxd: record.pxd, value });
      }
    }

    for (const metric of Object.keys(metricPoints)) {
      metricPoints[metric].sort((left, right) => left.pxd.localeCompare(right.pxd, undefined, { numeric: true }));
    }

    const distributions = metrics
      .map(metric => {
        const values = metricPoints[metric].map(point => point.value);
        if (!values.length) return null;
        const bounds = metricHistogramBounds(versionJudge?.judge_type, metric) || {
          minimum: Math.min(...values),
          maximum: Math.max(...values),
        };
        return {
          field: metric,
          count: values.length,
          minimum: Math.min(...values),
          maximum: Math.max(...values),
          mean: values.reduce((sum, value) => sum + value, 0) / values.length,
          histogramMinimum: bounds.minimum,
          histogramMaximum: bounds.maximum,
          histogram: buildHistogram(values, 10, bounds),
        };
      })
      .filter(Boolean);

    return {
      version,
      judgeType: versionJudge?.judge_type || null,
      releaseState: versionJudge?.release_state || null,
      totalPxds: versionJudge?.release_pxd_count || records.length,
      judgeRecords: records.length,
      metricPoints,
      distributions,
      availableMetrics: metrics.filter(metric => (metricPoints[metric] || []).length),
    };
  })();

  state.versionJudgeCache[version] = { promise };
  const data = await promise;
  state.versionJudgeCache[version] = { data };
  return data;
}

async function loadVersionMetadata(version) {
  const cached = state.versionMetadataCache[version];
  if (cached?.data) return cached.data;
  if (cached?.promise) return cached.promise;
  const promise = (async () => {
    const records = state.records.filter(record => (record.version || "Unknown") === version);
    const categories = new Map();

    await Promise.all(records.map(async record => {
      const sdrfPath = record.agentic.find(path => path.endsWith(`/${record.pxd}.sdrf.tsv`));
      if (!sdrfPath) return;
      try {
        const rows = parseDelimited(await fetchText(sdrfPath));
        if (!rows.length) return;
        const headers = rows[0].filter(Boolean);
        for (const header of headers) {
          if (!categories.has(header)) categories.set(header, new Set());
          categories.get(header).add(record.pxd);
        }
      } catch (_error) {
        // Skip unreadable SDRF files for this PXD.
      }
    }));

    const knownOrder = (state.summary?.metadata_categories || []).map(item => item.header);
    const headers = [...categories.keys()].sort((left, right) => {
      const leftIndex = knownOrder.indexOf(left);
      const rightIndex = knownOrder.indexOf(right);
      if (leftIndex !== -1 && rightIndex !== -1) return leftIndex - rightIndex;
      if (leftIndex !== -1) return -1;
      if (rightIndex !== -1) return 1;
      return left.localeCompare(right, undefined, { numeric: true });
    });
    const rows = headers.map(header => {
      const catalog = state.summary?.metadata_categories?.find(item => item.header === header);
      return [
        header,
        headerDefinition("SDRF", header),
        catalog?.requirement || "Not specified",
        catalog?.type || "Not specified",
        catalog?.ontology_accession || "Not specified",
        formatNumber(categories.get(header).size),
      ];
    });
    return {
      rows,
      observed: rows.length,
    };
  })();

  state.versionMetadataCache[version] = { promise };
  const data = await promise;
  state.versionMetadataCache[version] = { data };
  return data;
}

function qcStatus(value) {
  return value === "passed" ? "Pass"
    : value === "failed" ? "Failed"
      : value === "skipped" ? "Skipped"
        : value === "available" ? "Available"
          : value === "incompatible_judge_types" ? "Incompatible types"
          : value === "missing" ? "Missing"
            : "Not run";
}

function qcJudgeLabel(judge) {
  if (!judge || judge.status !== "available") return qcStatus(judge?.status);
  return `${qcStatus(judge.status)} (${judge.judge_type || "unknown"})`;
}

function renderVersionMetricPlots(versionData) {
  const container = document.querySelector("#qc-version-metric-plots");
  if (!container) return;
  for (const metric of versionData.availableMetrics) {
    const plot = document.querySelector(`#${metricPlotId(metric)}`);
    if (!plot) continue;
    const points = versionData.metricPoints[metric] || [];
    if (!points.length) {
      plot.textContent = `No ${metric} values are available for this version.`;
      continue;
    }
    if (!globalThis.Plotly) {
      plot.textContent = "Interactive plotting library is unavailable.";
      continue;
    }
    const width = Math.max(980, points.length * 20);
    globalThis.Plotly.newPlot(plot, [{
      type: "bar",
      x: points.map(point => point.pxd),
      y: points.map(point => point.value),
      marker: { color: "#007f6f" },
      hovertemplate: "<b>%{x}</b><br>Value: %{y:.4f}<extra></extra>",
    }], {
      width,
      margin: { l: 70, r: 24, t: 26, b: 140 },
      paper_bgcolor: "#fffdf8",
      plot_bgcolor: "#fffdf8",
      font: { family: "Georgia, Times New Roman, serif", color: "#17212b" },
      title: { text: `${metric} by PXD`, font: { size: 15 } },
      xaxis: { title: "PXD", tickangle: -60, tickfont: { family: "ui-monospace, monospace", size: 9 } },
      yaxis: { title: metric, zeroline: true, zerolinecolor: "#66727c" },
    }, { responsive: true, displaylogo: false });
  }
}

function qcComparisons(summary) {
  if (!summary) return [];
  if (Array.isArray(summary.comparisons)) return summary.comparisons;
  if (Array.isArray(summary.results)) {
    return [{
      comparison_id: summary.evaluated_commit || "legacy",
      baseline_version: summary.baseline_release_version || summary.fixture_version || "baseline",
      candidate_version: "candidate",
      summary: {
        shared_pxds: Array.isArray(summary.changed_pxds) ? summary.changed_pxds.length : 0,
        changed_sdrfs: Array.isArray(summary.changed_pxds) ? summary.changed_pxds.length : 0,
        unchanged_sdrfs: 0,
        judge_pairs_available: (summary.results || []).filter(result => result.judge?.status === "passed").length,
      },
      pxd_counts: {
        baseline: Array.isArray(summary.changed_pxds) ? summary.changed_pxds.length : 0,
        candidate: Array.isArray(summary.changed_pxds) ? summary.changed_pxds.length : 0,
        shared: Array.isArray(summary.changed_pxds) ? summary.changed_pxds.length : 0,
        baseline_only: 0,
        candidate_only: 0,
      },
      results: summary.results,
    }];
  }
  return [];
}

function activeQcComparison(summary) {
  const comparisons = qcComparisons(summary);
  if (!comparisons.length) return null;
  if (state.qcBaselineVersion && state.qcCandidateVersion) {
    const chosen = comparisons.find(comparison => comparison.baseline_version === state.qcBaselineVersion && comparison.candidate_version === state.qcCandidateVersion)
      || comparisons.find(comparison => comparison.baseline_version === state.qcCandidateVersion && comparison.candidate_version === state.qcBaselineVersion);
    if (chosen) {
      state.qcComparisonId = chosen.comparison_id;
      return chosen;
    }
  }
  const selected = comparisons.find(comparison => comparison.comparison_id === state.qcComparisonId);
  if (selected) return selected;
  const fallback = comparisons.find(comparison => comparison.comparison_id === summary.default_comparison_id) || comparisons[0];
  state.qcComparisonId = fallback.comparison_id;
  state.qcBaselineVersion = fallback.baseline_version;
  state.qcCandidateVersion = fallback.candidate_version;
  return fallback;
}

function qcCategoryMetricOptions(comparison) {
  const metrics = new Set();
  for (const result of comparison?.results || []) {
    for (const category of Object.values(result.judge_category_deltas || {})) {
      Object.keys(category).forEach(metric => metrics.add(metric));
    }
  }
  return [...metrics].sort();
}

function renderQcMetricPlot(comparison) {
  const container = document.querySelector("#qc-metric-plot");
  if (!container) return;
  if (!globalThis.Plotly) {
    container.textContent = "Interactive plotting library is unavailable.";
    return;
  }
  const traces = ["Biological", "Technical", "ExperimentalDesign"].map(category => {
    const points = [];
    for (const result of comparison?.results || []) {
      const delta = result.judge_category_deltas?.[category]?.[state.qcMetric];
      if (delta && Number.isFinite(delta[state.qcDeltaMode])) points.push({ pxd: result.pxd, ...delta });
    }
    return {
      name: category,
      type: "bar",
      x: points.map(point => point.pxd),
      y: points.map(point => point[state.qcDeltaMode]),
      customdata: points.map(point => [point.baseline, point.candidate, point.absolute_delta, point.relative_delta]),
      hovertemplate: "<b>%{x}</b><br>Category: " + category + "<br>Baseline: %{customdata[0]}<br>Candidate: %{customdata[1]}<br>Absolute delta: %{customdata[2]:+.4f}<br>Relative delta: %{customdata[3]:+.2%}<extra></extra>",
    };
  }).filter(trace => trace.x.length);
  if (!traces.length) {
    container.textContent = "No fresh post-store category judge deltas are available in this reviewed QC run.";
    return;
  }
  const label = state.qcDeltaMode === "relative_delta" ? "Relative change" : "Absolute change";
  globalThis.Plotly.newPlot(container, traces, {
    barmode: "group",
    margin: { l: 62, r: 20, t: 32, b: 130 },
    paper_bgcolor: "#fffdf8",
    plot_bgcolor: "#fffdf8",
    font: { family: "Georgia, Times New Roman, serif", color: "#17212b" },
    title: { text: `${state.qcMetric}: ${label} by PXD and metadata category`, font: { size: 16 } },
    xaxis: { title: "PXD", tickangle: -55, tickfont: { family: "ui-monospace, monospace", size: 9 } },
    yaxis: { title: label, tickformat: state.qcDeltaMode === "relative_delta" ? ".0%" : ".3f", zeroline: true, zerolinecolor: "#66727c" },
    legend: { orientation: "h", y: 1.15 },
  }, { responsive: true, displaylogo: false });
}

function comparisonQcContent(summary) {
  const comparisons = qcComparisons(summary || {});
  const comparison = activeQcComparison(summary || {});
  if (!comparison) {
    return "<p class=\"section-note\">A QC summary was published, but it does not contain a recognized comparison payload.</p>";
  }
  const results = Array.isArray(comparison.results) ? comparison.results : [];
  const rows = [["PXD", "SDRF", "Baseline judge", "Candidate judge", "judge_accuracy delta", "Category deltas"]];
  for (const result of results) {
    const accuracyDelta = result.judge_deltas?.judge_accuracy;
    const categoryCount = Object.keys(result.judge_category_deltas || {}).length;
    rows.push([
      result.pxd || "",
      result.sdrf_status === "missing" ? "Missing" : result.sdrf_changed ? "Changed" : "Same",
      qcJudgeLabel(result.baseline_judge),
      qcJudgeLabel(result.candidate_judge),
      accuracyDelta && Number.isFinite(accuracyDelta.absolute_delta) ? `${accuracyDelta.absolute_delta >= 0 ? "+" : ""}${accuracyDelta.absolute_delta.toFixed(4)}` : "-",
      categoryCount ? `${categoryCount} categories` : "-",
    ]);
  }
  const tableRows = rows.map((row, index) => index === 0 ? row : row.map(cell => esc(cell)));
  const tableHtml = `<div class="table-frame"><table><thead><tr>${tableRows[0].map(cell => `<th>${cell}</th>`).join("")}</tr></thead><tbody>${tableRows.slice(1).map(row => `<tr>${row.map(cell => `<td>${cell}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  const cards = [
    ["Baseline version", comparison.baseline_version || "Unknown"],
    ["Candidate version", comparison.candidate_version || "Unknown"],
    ["Shared PXDs", formatNumber(comparison.summary?.shared_pxds || 0)],
    ["Changed SDRFs", formatNumber(comparison.summary?.changed_sdrfs || 0)],
    ["Comparable judge pairs", formatNumber(comparison.summary?.judge_pairs_available || 0)],
    ["Incompatible judge pairs", formatNumber(comparison.summary?.judge_pairs_incompatible || 0)],
  ].map(([label, value]) => `<article class="stat-card"><span>${esc(label)}</span><strong class="qc-stat">${esc(value)}</strong><small>Static release comparison from versioned store artifacts</small></article>`).join("");
  const metrics = qcCategoryMetricOptions(comparison);
  const versionOptions = [...new Set(comparisons.flatMap(item => [item.baseline_version, item.candidate_version]))]
    .sort((left, right) => left.localeCompare(right, undefined, { numeric: true }));
  const comparisonSelector = `<div class="qc-controls"><label for="qc-baseline-version">Baseline</label><select id="qc-baseline-version">${versionOptions.map(version => `<option value="${esc(version)}"${version === comparison.baseline_version ? " selected" : ""}>${esc(version)}</option>`).join("")}</select><label for="qc-candidate-version">Candidate</label><select id="qc-candidate-version">${versionOptions.map(version => `<option value="${esc(version)}"${version === comparison.candidate_version ? " selected" : ""}>${esc(version)}</option>`).join("")}</select></div>`;
  const metricControls = metrics.length
    ? `<div class="qc-controls"><label for="qc-metric">Judge metric</label><select id="qc-metric">${metrics.map(metric => `<option value="${esc(metric)}"${metric === state.qcMetric ? " selected" : ""}>${esc(metric)}</option>`).join("")}</select><label for="qc-delta-mode">Change</label><select id="qc-delta-mode"><option value="relative_delta"${state.qcDeltaMode === "relative_delta" ? " selected" : ""}>Relative</option><option value="absolute_delta"${state.qcDeltaMode === "absolute_delta" ? " selected" : ""}>Absolute</option></select></div><div id="qc-metric-plot" class="qc-plot"></div>`
    : "<p class=\"section-note\">No category-level judge deltas are available for this published comparison.</p>";
  setTimeout(() => {
    const baselineSelect = document.querySelector("#qc-baseline-version");
    const candidateSelect = document.querySelector("#qc-candidate-version");
    const metricSelect = document.querySelector("#qc-metric");
    const deltaSelect = document.querySelector("#qc-delta-mode");
    if (baselineSelect) baselineSelect.addEventListener("change", () => {
      state.qcBaselineVersion = baselineSelect.value;
      renderOverview();
    });
    if (candidateSelect) candidateSelect.addEventListener("change", () => {
      state.qcCandidateVersion = candidateSelect.value;
      renderOverview();
    });
    if (metricSelect) metricSelect.addEventListener("change", () => { state.qcMetric = metricSelect.value; renderQcMetricPlot(activeQcComparison(summary)); });
    if (deltaSelect) deltaSelect.addEventListener("change", () => { state.qcDeltaMode = deltaSelect.value; renderQcMetricPlot(activeQcComparison(summary)); });
    renderQcMetricPlot(activeQcComparison(summary));
  }, 0);
  return `<p class="section-note">Static comparison of archived HAMLET release artifacts. Judge deltas are calculated only when both releases use the same judge type; cross-type pairs are shown as incompatible without metric deltas.</p><div class="stat-grid">${cards}</div>${comparisonSelector}${metricControls}${results.length ? `<div class="qc-table">${tableHtml}</div>` : "<p class=\"section-note\">No shared PXDs were found for this version pair.</p>"}`;
}

async function renderVersionQcDetails() {
  const container = document.querySelector("#qc-version-content");
  if (!container) return;
  selectDefaultQcVersion();
  if (!state.qcVersion) {
    container.innerHTML = "<p class=\"section-note\">No versions are available in this Store Explorer bundle.</p>";
    return;
  }
  const requestedVersion = state.qcVersion;
  container.innerHTML = "<p class=\"section-note\">Loading version-specific QC artifacts...</p>";
  const [judgeData, metadataData] = await Promise.all([
    loadVersionJudgeMetrics(requestedVersion),
    loadVersionMetadata(requestedVersion),
  ]);
  if (state.qcVersion !== requestedVersion) return;

  const versionCount = judgeData.totalPxds;
  const cards = [
    ["Selected version", requestedVersion],
    ["Release state", judgeData.releaseState === "in_progress" ? "In progress" : "Immutable"],
    ["PXDs in version", formatNumber(versionCount)],
    ["Judge type", judgeData.judgeType || "Unavailable"],
    ["Per-paper judge records", formatNumber(judgeData.judgeRecords)],
    ["Observed metadata headers", formatNumber(metadataData.observed)],
  ].map(([label, value]) => `<article class="stat-card"><span>${esc(label)}</span><strong class="qc-stat">${esc(value)}</strong><small>Version-specific QC summary</small></article>`).join("");

  const distributions = judgeData.distributions.length
    ? `<div class="histogram-grid">${judgeData.distributions.map(histogramCard).join("")}</div>`
    : "<p class=\"section-note\">No per-paper judge metrics were published for this version.</p>";

  const metricCards = judgeData.availableMetrics.length
    ? `<div id="qc-version-metric-plots" class="metric-plot-stack">${judgeData.availableMetrics.map(metric => `<article class="metric-plot-card"><h4>${esc(metric)}</h4><p class="section-note">Absolute values across all PXDs in ${esc(requestedVersion)}.</p><div class="plot-scroll"><div id="${esc(metricPlotId(metric))}" class="qc-plot qc-plot-compact"></div></div></article>`).join("")}</div>`
    : "<p class=\"section-note\">No absolute metric values were found for this version.</p>";

  const metadataRows = [["SDRF header", "Definition", "Requirement", "Type", "Ontology accession", "PXDs"], ...metadataData.rows];
  const metadataSection = metadataData.rows.length
    ? tableContent(metadataRows, "SDRF metadata categories")
    : "<p class=\"section-note\">No SDRF headers were detected for this version.</p>";

  const judgeLabel = judgeData.judgeType === "sdrf_judge" ? "SDRF judge" : judgeData.judgeType === "llm_judge" ? "LLM judge" : "Judge";
  const releaseStateText = judgeData.releaseState === "in_progress" ? "an in-progress snapshot" : "an immutable release";
  container.innerHTML = `<div class="stat-grid">${cards}</div>${section("HAMLET SDRFs by version", "Counts shown below are scoped to the selected version.", `<p class=\"section-note\"><strong>${esc(requestedVersion)}</strong> is ${releaseStateText} with ${esc(formatNumber(versionCount))} versioned SDRFs.</p>`)}${section(`${judgeLabel} distributions`, `Histograms summarize ${formatNumber(judgeData.judgeRecords)} per-paper ${judgeLabel.toLowerCase()} records for HAMLET ${requestedVersion}. Each metric uses fixed bin limits across all ${judgeLabel.toLowerCase()} versions.`, distributions)}${section(`${judgeLabel} metrics`, "Absolute per-PXD metric values. Plots are interactive and horizontally scrollable.", metricCards)}${section("Available SDRF metadata categories", "Headers observed in final HAMLET SDRFs for the selected version.", metadataSection)}`;
  setTimeout(() => renderVersionMetricPlots(judgeData), 0);
}

function qcOverview(summary) {
  selectDefaultQcVersion();
  const versions = sortedVersions();
  const versionControls = `<div class="qc-controls"><label for="qc-version-select">Version</label><select id="qc-version-select">${versions.map(version => `<option value="${esc(version)}"${version === state.qcVersion ? " selected" : ""}>${esc(version)}</option>`).join("")}</select></div>`;
  const comparisonPanel = summary
    ? comparisonQcContent(summary)
    : "<p class=\"section-note\">No reviewed QC summary has been published with this Store Explorer build for comparison mode.</p>";
  setTimeout(() => {
    document.querySelectorAll("[data-qc-tab]").forEach(button => button.addEventListener("click", () => {
      state.qcTab = button.dataset.qcTab;
      renderOverview();
    }));
    const versionSelect = document.querySelector("#qc-version-select");
    if (versionSelect) {
      versionSelect.addEventListener("change", () => {
        state.qcVersion = versionSelect.value;
        renderVersionQcDetails();
      });
    }
    if (state.qcTab === "version") renderVersionQcDetails();
  }, 0);

  return section("Quality control", "Review either a single version or a baseline-vs-candidate comparison.", `<div class="qc-tabs"><button class="qc-tab ${state.qcTab === "version" ? "active" : ""}" type="button" data-qc-tab="version">Version QC</button><button class="qc-tab ${state.qcTab === "comparison" ? "active" : ""}" type="button" data-qc-tab="comparison">Comparison QC</button></div><div class="qc-tab-panel ${state.qcTab === "version" ? "active" : ""}" id="qc-tab-version">${versionControls}<div id="qc-version-content"><p class="section-note">Select a version to load version-specific QC details.</p></div></div><div class="qc-tab-panel ${state.qcTab === "comparison" ? "active" : ""}" id="qc-tab-comparison">${comparisonPanel}</div>`);
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
  detail.innerHTML = `<header class="record-header overview-header"><div><p class="eyebrow">Store overview</p><h2>HAMLET record summary</h2></div><span class="availability">${esc(formatNumber(summary.total_pxds))} catalogued PXDs</span></header>${qcOverview(state.qcSummary)}`;
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
  const [response, definitionsResponse, summaryResponse, qcSummary] = await Promise.all([fetch("data/store-index.json"), fetch("table-definitions.json"), fetch("data/site-summary.json"), fetchOptionalJson("qc-summary.json")]);
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
  state.qcSummary = qcSummary;
  state.records = index.pxds;
  selectDefaultQcVersion();
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