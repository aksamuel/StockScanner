import { enhanceFilterSelect } from "./searchable-filter.js";

const optionOrder = new Intl.Collator("en", { numeric: true, sensitivity: "base" });
const reportControllers = new WeakMap();

export function setFilterOptions(select, values, allLabel = "All stocks") {
  const choices = [...new Set(values.map(value => String(value || "").trim()).filter(Boolean))]
    .sort(optionOrder.compare);
  const selected = choices.includes(select.value) ? select.value : "";
  const options = [["", allLabel], ...choices.map(value => [value, value])];
  if (select.options.length !== options.length || options.some(([value, label], index) =>
    select.options[index]?.value !== value || select.options[index]?.textContent !== label)) {
    select.replaceChildren(...options.map(([value, label]) => {
      const option = select.ownerDocument.createElement("option");
      option.value = value;
      option.textContent = label;
      return option;
    }));
  }
  select.value = selected;
  enhanceFilterSelect(select);
  return selected;
}

function stockRows(table) {
  if (!table) return [];
  const symbolIndex = [...table.querySelectorAll("thead th")]
    .findIndex(header => header.textContent.trim() === "Symbol");
  return [...table.querySelectorAll("tbody tr")].map(row => ({
    row,
    symbol: (row.dataset.symbol || row.querySelector(".symbol-name")?.textContent
      || row.cells[symbolIndex]?.textContent || "").trim().toUpperCase(),
  })).filter(item => item.symbol);
}

function reportSelect(id, root) {
  const existing = root.getElementById(id);
  if (!existing) return null;
  if (existing.tagName === "SELECT") return existing;
  // Archived reports share auth.js, so upgrade their older text fields too.
  const select = root.createElement("select");
  select.id = existing.id;
  select.className = existing.className;
  select.setAttribute("aria-label", "Select a stock");
  existing.replaceWith(select);
  return select;
}

export function installReportStockFilters(root = document) {
  if (reportControllers.has(root)) {
    reportControllers.get(root).forEach(refresh => refresh());
    return;
  }
  const report = reportSelect("filterInput", root);
  const kpi = reportSelect("kpiStockSearch", root);
  if (!report && !kpi) return;
  const refreshers = [];
  reportControllers.set(root, refreshers);
  const style = root.createElement("style");
  style.dataset.reportStockFilters = "";
  style.textContent = `
    .filter-bar select { width: 300px; max-width: 100%; min-height: 40px;
      padding: 8px 12px; border-radius: 6px; border: 1px solid #37474f;
      color: #e0e0e0; background: #1a2a3a; font: inherit; }
    .filter-bar select:focus-visible, .kpi-stock-search:focus-visible {
      outline: 2px solid #4fc3f7; outline-offset: 2px; }
    @media (max-width: 720px) { .filter-bar select { width: 100%; } }
  `;
  root.head.appendChild(style);

  if (report) {
    function filterReport() {
      const table = root.querySelector(".tab-content.active table");
      const entries = stockRows(table);
      const selected = setFilterOptions(report, entries.filter(({row}) => !row.hidden).map(item => item.symbol));
      entries.forEach(({row, symbol}) => { row.style.display = !selected || symbol === selected ? "" : "none"; });
      window.renumberVisibleRanks?.(table);
    }
    // Existing report controls call these global functions, including archives.
    window.filterTable = filterReport;
    const switchTab = window.switchTab;
    if (switchTab) window.switchTab = (...args) => { switchTab(...args); filterReport(); };
    report.addEventListener("change", filterReport);
    root.addEventListener("click", event => {
      if (event.target.closest?.(".personal-filter-toggle")) filterReport();
    });
    refreshers.push(filterReport);
    filterReport();
  }

  if (kpi) {
    kpi.removeEventListener("input", window.filterKpiStockRows);
    function filterKpi() {
      const category = root.querySelector('.kpi-card[aria-expanded="true"]')?.dataset.kpiFilter || "all";
      const entries = stockRows(root.getElementById("kpiStockTable"));
      const matchesCategory = row => category === "all" || row.dataset.kpiCategory === category;
      const selected = setFilterOptions(kpi, entries.filter(({row}) => matchesCategory(row)).map(item => item.symbol));
      let visible = 0;
      entries.forEach(({row, symbol}) => {
        row.hidden = !matchesCategory(row) || Boolean(selected && symbol !== selected);
        if (!row.hidden) visible += 1;
      });
      root.getElementById("kpiDetailsCount").textContent = `${visible} stock${visible === 1 ? "" : "s"} shown`;
    }
    window.filterKpiStockRows = filterKpi;
    kpi.addEventListener("change", filterKpi);
    refreshers.push(filterKpi);
    filterKpi();
  }
}

// Reports also load this module directly, including archives without auth.js.
if (typeof document !== "undefined") installReportStockFilters();
