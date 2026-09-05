import { createClient } from "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.112.3/+esm";
import { annotateBoughtAnalysis, purchaseBasisBySymbol } from "./bought-price.js";
import { installReportStockFilters } from "./table-filters.js";

const SUPABASE_URL = "https://cszzbkssxxgwgafwuonc.supabase.co";
const SUPABASE_PUBLISHABLE_KEY = "sb_publishable_VnhkG4H4acjm2Hp1k5tzyw_I9xtUrGI";
const APP_ROOT = "/StockScanner/";
const ADMIN_EMAIL = "aaksamuel@zohomail.com";

const supabase = createClient(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, {
  auth: {
    persistSession: true,
    autoRefreshToken: true,
    detectSessionInUrl: true,
  },
});

function loginUrl() {
  const next = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  return `${APP_ROOT}login.html?next=${encodeURIComponent(next)}`;
}

function showPage() {
  document.documentElement.classList.add("auth-ready");
}

const personalTopTwentyFilterState = {
  showAlreadyBought: false,
  showExceptions: false,
};

function addPersonalFilterStyles() {
  if (document.querySelector("style[data-stockscanner-personal-filter]")) return;
  const style = document.createElement("style");
  style.dataset.stockscannerPersonalFilter = "";
  style.textContent = `
    .personal-filter-controls {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
    }
    .personal-filter-item {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }
    .personal-filter-toggle {
      padding: 7px 14px;
      color: #e0e0e0;
      background: #24384a;
      border: 1px solid #81d4fa;
      border-radius: 5px;
      cursor: pointer;
    }
    .personal-filter-toggle:hover:not(:disabled) { filter: brightness(1.15); }
    .personal-filter-toggle:disabled { cursor: default; opacity: 0.6; }
    .personal-filter-status { color: #90a4ae; font-size: 0.8rem; }
    .already-bought-badge,
    .personal-exception-badge {
      display: inline-block;
      margin-left: 6px;
      padding: 1px 6px;
      color: #b9f6ca;
      background: #1b5e20;
      border: 1px solid #66bb6a;
      border-radius: 999px;
      font-size: 0.68rem;
      font-weight: 700;
      vertical-align: middle;
    }
    .personal-exception-badge {
      color: #ffe0b2;
      background: #6d4c2f;
      border-color: #ffb74d;
    }
  `;
  document.head.appendChild(style);
}

function topTwentyRows() {
  return [...document.querySelectorAll(
    "#topTable tbody tr, #top20DetailsTable tbody tr",
  )];
}

function rowSymbol(row) {
  return (
    row.dataset.symbol
    || row.querySelector(".symbol-name")?.textContent
    || row.cells[0]?.textContent
    || ""
  ).trim().toUpperCase();
}

function addAlreadyBoughtBadge(row) {
  if (row.querySelector(".already-bought-badge")) return;
  const symbolCell = row.querySelector(".symbol-name")?.closest("td") || row.cells[0];
  if (!symbolCell) return;
  const badge = document.createElement("span");
  badge.className = "already-bought-badge";
  badge.textContent = "Already Bought";
  symbolCell.append(" ", badge);
}

function addPersonalExceptionBadge(row) {
  if (row.querySelector(".personal-exception-badge")) return;
  const symbolCell = row.querySelector(".symbol-name")?.closest("td") || row.cells[0];
  if (!symbolCell) return;
  const badge = document.createElement("span");
  badge.className = "personal-exception-badge";
  badge.textContent = "My Exception";
  symbolCell.append(" ", badge);
}

function updatePersonalRowVisibility() {
  topTwentyRows().forEach((row) => {
    const hideBought = row.dataset.alreadyBought === "true"
      && !personalTopTwentyFilterState.showAlreadyBought;
    const hideException = row.dataset.personalException === "true"
      && !personalTopTwentyFilterState.showExceptions;
    row.hidden = hideBought || hideException;
  });
  document.querySelectorAll("#topTable").forEach((table) => {
    window.renumberVisibleRanks?.(table);
  });
}

function personalFilterContainer(target) {
  if (!target) return null;
  const existing = target.querySelector(":scope > .personal-filter-controls");
  if (existing) return existing;
  const container = document.createElement("div");
  container.className = "personal-filter-controls";
  target.appendChild(container);
  return container;
}

function addPersonalFilterControl(target, options) {
  const controls = personalFilterContainer(target);
  if (!controls || controls.querySelector(`[data-filter-kind="${options.kind}"]`)) {
    return null;
  }
  const item = document.createElement("div");
  item.className = "personal-filter-item";
  item.dataset.filterKind = options.kind;

  const button = document.createElement("button");
  button.type = "button";
  button.className = "personal-filter-toggle";
  button.setAttribute("aria-pressed", "false");

  const status = document.createElement("span");
  status.className = "personal-filter-status";

  function render(showRows) {
    personalTopTwentyFilterState[options.stateKey] = showRows;
    updatePersonalRowVisibility();
    button.dataset.showRows = String(showRows);
    button.setAttribute("aria-pressed", String(showRows));
    button.textContent = showRows
      ? `${options.hideLabel} (${options.count})`
      : `${options.showLabel} (${options.count})`;
    status.textContent = showRows ? options.visibleStatus : options.hiddenStatus;
  }

  button.addEventListener("click", () => {
    render(button.dataset.showRows !== "true");
  });
  item.append(button, status);
  controls.appendChild(item);
  render(false);
  if (options.count === 0) {
    button.disabled = true;
    button.textContent = `${options.emptyLabel} (0)`;
    status.textContent = options.emptyStatus;
  }
  return button;
}

async function readPersonalPurchaseRows(query) {
  const data = [];
  const pageSize = 1000;
  for (let offset = 0; ; offset += pageSize) {
    const result = await query().order("id").range(offset, offset + pageSize - 1);
    if (result.error) return result;
    data.push(...(result.data || []));
    if ((result.data || []).length < pageSize) return { data, error: null };
  }
}

async function applyPersonalTopTwentyFilters(user) {
  const rows = topTwentyRows();
  const page = window.location.pathname.split("/").filter(Boolean).pop();
  const showPurchasePrices = page === "technical.html" || page === "analysts.html";
  if (!rows.length && !showPurchasePrices) return;

  const today = new Date().toISOString().slice(0, 10);
  const [boughtResult, portfolioResult, exceptionResult] = await Promise.all([
    readPersonalPurchaseRows(() => supabase
      .from("user_bought_selections")
      .select(showPurchasePrices ? "symbol,quantity,buy_price" : "symbol")
      .eq("user_id", user.id)),
    readPersonalPurchaseRows(() => supabase
      .from("user_portfolio_holdings")
      .select(showPurchasePrices ? "symbol,quantity,buy_price,currency" : "symbol")
      .eq("user_id", user.id)),
    supabase
      .from("user_exceptions")
      .select("symbol,date_from,date_to")
      .eq("user_id", user.id)
      .lte("date_from", today)
      .gte("date_to", today),
  ]);

  if (boughtResult.error) throw boughtResult.error;
  if (portfolioResult.error) throw portfolioResult.error;
  if (exceptionResult.error) throw exceptionResult.error;

  const boughtSymbols = new Set(
    [...(boughtResult.data || []), ...(portfolioResult.data || [])]
      .map((item) => String(item.symbol || "").trim().toUpperCase()),
  );
  const exceptionSymbols = new Set(
    (exceptionResult.data || [])
      .map((item) => String(item.symbol || "").trim().toUpperCase()),
  );
  const boughtRows = rows.filter((row) => boughtSymbols.has(rowSymbol(row)));
  const exceptionRows = rows.filter((row) => exceptionSymbols.has(rowSymbol(row)));
  boughtRows.forEach((row) => {
    row.dataset.alreadyBought = "true";
    addAlreadyBoughtBadge(row);
  });
  exceptionRows.forEach((row) => {
    row.dataset.personalException = "true";
    addPersonalExceptionBadge(row);
  });

  addPersonalFilterStyles();
  if (showPurchasePrices) {
    annotateBoughtAnalysis(purchaseBasisBySymbol(boughtResult.data, portfolioResult.data), page);
  }
  const targets = [
    document.querySelector(".filter-bar"),
    document.querySelector(".top20-drilldown"),
  ].filter(Boolean);

  targets.forEach((target) => {
    addPersonalFilterControl(target, {
      kind: "bought",
      stateKey: "showAlreadyBought",
      count: boughtRows.length,
      showLabel: "Show Already Bought",
      hideLabel: "Hide Already Bought",
      emptyLabel: "Already Bought",
      hiddenStatus: "Your bought selections are hidden by default.",
      visibleStatus: "Your bought selections are visible.",
      emptyStatus: "No bought selections are present in this Top 20.",
    });
    addPersonalFilterControl(target, {
      kind: "exceptions",
      stateKey: "showExceptions",
      count: exceptionRows.length,
      showLabel: "Show My Exceptions",
      hideLabel: "Hide My Exceptions",
      emptyLabel: "My Exceptions",
      hiddenStatus: "Your active personal exceptions are hidden by default.",
      visibleStatus: "Your active personal exceptions are visible.",
      emptyStatus: "No active personal exceptions are present in this Top 20.",
    });
  });
}

function localDateString(date) {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

function installPersonalExceptionApi(user) {
  window.stockscannerPersonalExceptions = {
    add: async (symbols, reason = "Added from scanner dashboard", durationDays = 30) => {
      const uniqueSymbols = [...new Set(
        (symbols || []).map((symbol) => String(symbol).trim().toUpperCase()),
      )].filter((symbol) => /^[A-Z0-9][A-Z0-9.-]{0,14}$/.test(symbol));
      if (!uniqueSymbols.length) throw new Error("Select at least one valid ticker.");
      if (uniqueSymbols.length > 50) throw new Error("Select no more than 50 tickers per request.");
      const dateFrom = new Date();
      const dateTo = new Date(dateFrom);
      dateTo.setDate(dateTo.getDate() + durationDays);
      const records = uniqueSymbols.map((symbol) => ({
        user_id: user.id,
        symbol,
        reason: String(reason || "").slice(0, 500) || null,
        date_from: localDateString(dateFrom),
        date_to: localDateString(dateTo),
      }));
      const { error } = await supabase
        .from("user_exceptions")
        .upsert(records, { onConflict: "user_id,symbol" });
      if (error) throw error;
      return records.length;
    },
  };
}

function installPersonalBoughtApi(user) {
  window.stockscannerBoughtSelections = {
    add: async (selections) => {
      const today = localDateString(new Date());
      const normalized = new Map();
      for (const selection of selections || []) {
        const symbol = String(selection.symbol || "").trim().toUpperCase();
        const quantity = Number(selection.quantity);
        const buyPrice = Number(selection.buy_price);
        if (!/^[A-Z0-9][A-Z0-9.-]{0,14}$/.test(symbol)) continue;
        normalized.set(symbol, {
          user_id: user.id,
          symbol,
          quantity: Number.isFinite(quantity) && quantity > 0 ? quantity : 1,
          buy_price: Number.isFinite(buyPrice) && buyPrice >= 0 ? buyPrice : null,
          bought_on: selection.bought_on || today,
          notes: String(selection.notes || "Added from scanner candidate list").slice(0, 500),
        });
      }
      const records = [...normalized.values()];
      if (!records.length) throw new Error("Select at least one valid ticker.");
      if (records.length > 50) throw new Error("Select no more than 50 tickers at once.");
      const { error } = await supabase
        .from("user_bought_selections")
        .upsert(records, { onConflict: "user_id,symbol" });
      if (error) throw error;
      return records.length;
    },
  };
}

async function updatePresence(user, signedOut = false) {
  const now = new Date().toISOString();
  const pagePath = `${window.location.pathname}${window.location.search}`.slice(0, 500);

  return supabase.from("user_presence").upsert({
    user_id: user.id,
    last_seen_at: now,
    signed_out_at: signedOut ? now : null,
    last_page: pagePath,
  }, { onConflict: "user_id" });
}

async function recordActivity(user, eventType) {
  const pagePath = `${window.location.pathname}${window.location.search}`.slice(0, 500);

  await Promise.all([
    supabase.from("user_activity_events").insert({
      user_id: user.id,
      event_type: eventType,
      page_path: pagePath,
    }),
    updatePresence(user, eventType === "logout"),
  ]);
}

function addNavigationDrawerStyles() {
  if (document.querySelector("style[data-stockscanner-navigation]")) return;
  const style = document.createElement("style");
  style.dataset.stockscannerNavigation = "";
  style.textContent = `
    .stockscanner-drawer-ready body {
      padding-top: 12px !important;
    }
    .stockscanner-drawer-ready .page-header {
      min-height: 38px;
      padding-left: 94px;
    }
    .stockscanner-drawer-ready header h1 {
      padding-inline: 86px;
    }
    .stockscanner-drawer-ready .dashboard-nav,
    .stockscanner-drawer-ready .page-nav,
    .stockscanner-drawer-ready .page-header > a[href$="admin.html"],
    .stockscanner-drawer-ready .page-header > a[href$="users.html"] {
      display: none !important;
    }
    body.stockscanner-drawer-open { overflow: hidden; }
    .stockscanner-menu-toggle {
      position: fixed;
      top: 12px;
      left: 12px;
      z-index: 100001;
      display: inline-flex;
      min-height: 36px;
      align-items: center;
      gap: 8px;
      padding: 6px 10px;
      border: 1px solid #4fc3f7;
      border-radius: 8px;
      color: #e0f7fa;
      background: #10212d;
      box-shadow: 0 4px 16px #0008;
      font: 700 14px/1.1 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      cursor: pointer;
    }
    .stockscanner-menu-toggle:hover,
    .stockscanner-menu-toggle:focus-visible { background: #193247; }
    .stockscanner-menu-icon { font-size: 18px; line-height: 1; }
    .stockscanner-drawer-overlay {
      position: fixed;
      inset: 0;
      z-index: 100002;
      background: #0009;
      backdrop-filter: blur(2px);
    }
    .stockscanner-drawer-overlay[hidden] { display: none; }
    .stockscanner-navigation-drawer {
      position: fixed;
      inset: 0 auto 0 0;
      z-index: 100003;
      display: flex;
      width: min(86vw, 330px);
      flex-direction: column;
      padding: 18px;
      border-right: 1px solid #3b5368;
      color: #e0e0e0;
      background: #0f1923;
      box-shadow: 10px 0 32px #000a;
      transform: translateX(-105%);
      visibility: hidden;
      transition: transform 180ms ease, visibility 180ms;
    }
    .stockscanner-navigation-drawer.is-open {
      transform: translateX(0);
      visibility: visible;
    }
    .stockscanner-drawer-header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
      padding-bottom: 14px;
      border-bottom: 1px solid #334b5f;
    }
    .stockscanner-drawer-title {
      margin: 0;
      color: #4fc3f7;
      font: 750 1.15rem/1.2 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    .stockscanner-drawer-user {
      display: block;
      max-width: 235px;
      margin-top: 5px;
      overflow: hidden;
      color: #90a4ae;
      font: 12px/1.35 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .stockscanner-drawer-close {
      display: grid;
      min-width: 38px;
      min-height: 38px;
      padding: 0;
      place-items: center;
      border: 1px solid #546e7a;
      border-radius: 7px;
      color: #e0e0e0;
      background: #1a2a3a;
      font: 24px/1 sans-serif;
      cursor: pointer;
    }
    .stockscanner-drawer-nav {
      display: grid;
      gap: 5px;
      margin: 14px -6px;
      overflow-y: auto;
    }
    .stockscanner-drawer-section {
      margin: 12px 10px 3px;
      color: #78909c;
      font: 700 11px/1.2 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: .08em;
      text-transform: uppercase;
    }
    .stockscanner-drawer-link {
      display: block;
      padding: 10px 12px;
      border: 1px solid transparent;
      border-radius: 7px;
      color: #b3e5fc;
      font: 650 14px/1.25 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      text-decoration: none;
    }
    .stockscanner-drawer-link:hover,
    .stockscanner-drawer-link:focus-visible { background: #1a2a3a; }
    .stockscanner-drawer-link[aria-current="page"] {
      border-color: #4fc3f7;
      color: #10212d;
      background: #4fc3f7;
    }
    .stockscanner-drawer-signout {
      width: 100%;
      min-height: 42px;
      margin-top: auto;
      padding: 9px 12px;
      border: 1px solid #ef9a9a;
      border-radius: 7px;
      color: #ffcdd2;
      background: #3c1f25;
      font: 700 14px/1.2 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      cursor: pointer;
    }
    @media (max-width: 480px) {
      .stockscanner-menu-toggle { top: 10px; left: 10px; width: 38px; padding-inline: 7px; }
      .stockscanner-menu-toggle > span:last-child { display: none; }
      .stockscanner-drawer-ready .page-header { padding-left: 48px; }
      .stockscanner-drawer-ready header h1 { padding-inline: 44px; }
      .stockscanner-navigation-drawer { width: min(91vw, 330px); }
    }
    @media (prefers-reduced-motion: reduce) {
      .stockscanner-navigation-drawer { transition: none; }
    }
  `;
  document.head.appendChild(style);
}

function addNavigationDrawer(user) {
  addNavigationDrawerStyles();
  document.documentElement.classList.add("stockscanner-drawer-ready");

  const displayName = user.user_metadata?.full_name
    || user.user_metadata?.name
    || user.email
    || "Signed in user";
  const isAdmin = (user.email || "").toLowerCase() === ADMIN_EMAIL;
  const menuItems = [
    ["Scanner", "KPI dashboard", "index.html"],
    ["Scanner", "Technical analysis", "technical.html"],
    ["Scanner", "Analysts rating", "analysts.html"],
    ["Scanner", "Bought candidates", "bought-selection.html"],
    ["Market data", "Hourly & daily prices", "market-prices.html"],
    ["Market data", "Database overview", "database.html"],
    ["My lists", "My exceptions", "my-exceptions.html"],
    ["My lists", "My bought list", "my-bought-selection.html"],
    ["My lists", "Portfolio analysis", "portfolio-analysis.html"],
    ["Support", "Help & FAQ", "help.html"],
  ];
  if (isAdmin) {
    menuItems.push(
      ["Administration", "Admin dashboard", "admin.html"],
      ["Administration", "Manage users", "users.html"],
    );
  }

  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "stockscanner-menu-toggle";
  toggle.setAttribute("aria-controls", "stockscanner-navigation-drawer");
  toggle.setAttribute("aria-expanded", "false");
  toggle.setAttribute("aria-label", "Open navigation menu");
  toggle.innerHTML = '<span class="stockscanner-menu-icon" aria-hidden="true">☰</span><span>Menu</span>';

  const overlay = document.createElement("div");
  overlay.className = "stockscanner-drawer-overlay";
  overlay.hidden = true;

  const drawer = document.createElement("aside");
  drawer.id = "stockscanner-navigation-drawer";
  drawer.className = "stockscanner-navigation-drawer";
  drawer.setAttribute("aria-label", "StockScanner navigation");
  drawer.setAttribute("aria-hidden", "true");

  const header = document.createElement("div");
  header.className = "stockscanner-drawer-header";
  const heading = document.createElement("div");
  const title = document.createElement("p");
  title.className = "stockscanner-drawer-title";
  title.textContent = "StockScanner";
  const identity = document.createElement("span");
  identity.className = "stockscanner-drawer-user";
  identity.textContent = displayName;
  identity.title = user.email || displayName;
  heading.append(title, identity);

  const close = document.createElement("button");
  close.type = "button";
  close.className = "stockscanner-drawer-close";
  close.setAttribute("aria-label", "Close navigation menu");
  close.textContent = "×";
  header.append(heading, close);

  const navigation = document.createElement("nav");
  navigation.className = "stockscanner-drawer-nav";
  navigation.setAttribute("aria-label", "Main navigation");
  const currentPage = window.location.pathname.split("/").filter(Boolean).pop() || "index.html";
  let lastSection = "";
  for (const [sectionName, label, filename] of menuItems) {
    if (sectionName !== lastSection) {
      const section = document.createElement("p");
      section.className = "stockscanner-drawer-section";
      section.textContent = sectionName;
      navigation.appendChild(section);
      lastSection = sectionName;
    }
    const link = document.createElement("a");
    link.className = "stockscanner-drawer-link";
    link.href = `${APP_ROOT}${filename}`;
    link.textContent = label;
    if (currentPage === filename) link.setAttribute("aria-current", "page");
    navigation.appendChild(link);
  }

  const signOut = document.createElement("button");
  signOut.type = "button";
  signOut.className = "stockscanner-drawer-signout";
  signOut.textContent = "Sign out";
  signOut.addEventListener("click", async () => {
    signOut.disabled = true;
    await recordActivity(user, "logout").catch(() => {});
    await supabase.auth.signOut({ scope: "local" });
    window.location.replace(`${APP_ROOT}login.html`);
  });

  drawer.append(header, navigation, signOut);
  document.body.append(toggle, overlay, drawer);

  const closeDrawer = (returnFocus = true) => {
    drawer.classList.remove("is-open");
    drawer.setAttribute("aria-hidden", "true");
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-label", "Open navigation menu");
    overlay.hidden = true;
    document.body.classList.remove("stockscanner-drawer-open");
    if (returnFocus) toggle.focus();
  };
  const openDrawer = () => {
    overlay.hidden = false;
    drawer.classList.add("is-open");
    drawer.setAttribute("aria-hidden", "false");
    toggle.setAttribute("aria-expanded", "true");
    toggle.setAttribute("aria-label", "Close navigation menu");
    document.body.classList.add("stockscanner-drawer-open");
    close.focus();
  };

  toggle.addEventListener("click", () => {
    if (drawer.classList.contains("is-open")) closeDrawer();
    else openDrawer();
  });
  close.addEventListener("click", () => closeDrawer());
  overlay.addEventListener("click", () => closeDrawer());
  navigation.addEventListener("click", (event) => {
    if (event.target.closest("a")) closeDrawer(false);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && drawer.classList.contains("is-open")) {
      closeDrawer();
    }
  });
}

function reorderTechnicalAnalysisColumns() {
  const page = window.location.pathname.split("/").filter(Boolean).pop();
  if (page !== "technical.html") return;
  document.querySelectorAll("table").forEach((table) => {
    const headerRow = table.querySelector("thead tr");
    if (!headerRow) return;
    const names = [...headerRow.children].map((cell) => cell.textContent.trim());
    const desired = ["Rank", "Symbol", "Entry", "Target 1", "Target 2", "Target 3"];
    if (!desired.every((name) => names.includes(name))) return;
    const remaining = names.filter((name) => !desired.includes(name));
    const order = [...desired, ...remaining].map((name) => names.indexOf(name));
    if (order.every((sourceIndex, targetIndex) => sourceIndex === targetIndex)) return;
    const reorder = (row) => {
      const cells = [...row.children];
      order.forEach((index) => row.appendChild(cells[index]));
    };
    reorder(headerRow);
    table.querySelectorAll("tbody tr").forEach(reorder);
  });
}

function installSharedTableSorting() {
  const page = window.location.pathname.split("/").filter(Boolean).pop() || "index.html";
  const generatedReportPages = new Set(["index.html", "technical.html", "analysts.html", "bought-selection.html"]);
  if (window.stockscannerNativeTableSorting || generatedReportPages.has(page)) return;
  if (!document.querySelector("style[data-stockscanner-table-sorting]")) {
    const style = document.createElement("style");
    style.dataset.stockscannerTableSorting = "";
    style.textContent = `
      .stockscanner-sort-button {
        display: inline-flex;
        width: 100%;
        min-height: 32px;
        align-items: center;
        gap: 6px;
        padding: 3px 0;
        border: 0;
        color: inherit;
        background: transparent;
        font: inherit;
        font-weight: inherit;
        text-align: left;
        cursor: pointer;
      }
      .stockscanner-sort-button::after { content: "↕"; color: #78909c; font-size: .78em; }
      th[aria-sort="ascending"] .stockscanner-sort-button::after { content: "▲"; color: #81d4fa; }
      th[aria-sort="descending"] .stockscanner-sort-button::after { content: "▼"; color: #81d4fa; }
      .stockscanner-sort-button:focus-visible { outline: 2px solid #4fc3f7; outline-offset: 2px; }
    `;
    document.head.appendChild(style);
  }

  const missingLabels = new Set(["", "—", "-", "n/a", "na", "unavailable", "pending", "pending close", "unknown"]);
  const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

  function sortValue(cell) {
    const raw = cell?.dataset.sortValue ?? cell?.textContent ?? "";
    const text = raw.replace(/\s+/g, " ").trim();
    if (missingLabels.has(text.toLowerCase())) return { missing: true, value: null };

    const normalizedNumber = text
      .replace(/^(?:USD|CAD|EUR|GBP|AUD|JPY)\s+/i, "")
      .replace(/[$£€¥,%]/g, "")
      .replace(/,/g, "")
      .trim();
    if (/^[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:\s*(?:days?|shares?))?$/i.test(normalizedNumber)) {
      return { missing: false, value: Number.parseFloat(normalizedNumber) };
    }

    if (/^\d{4}-\d{2}-\d{2}(?:[T\s].*)?$/.test(text)
        || /^\d{1,2}[\/-]\d{1,2}[\/-]\d{2,4}(?:\s.*)?$/.test(text)
        || /^[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}/.test(text)) {
      const timestamp = Date.parse(text);
      if (Number.isFinite(timestamp)) return { missing: false, value: timestamp };
    }
    return { missing: false, value: text };
  }

  function compareCells(leftCell, rightCell, direction) {
    const left = sortValue(leftCell);
    const right = sortValue(rightCell);
    if (left.missing || right.missing) {
      if (left.missing && right.missing) return 0;
      return left.missing ? 1 : -1;
    }
    const comparison = typeof left.value === "number" && typeof right.value === "number"
      ? left.value - right.value
      : collator.compare(String(left.value), String(right.value));
    return direction === "ascending" ? comparison : -comparison;
  }

  function applySort(table) {
    const column = Number(table.dataset.stockscannerSortColumn);
    const direction = table.dataset.stockscannerSortDirection;
    if (!Number.isInteger(column) || !direction) return;
    for (const body of table.tBodies) {
      const current = [...body.rows];
      const sorted = current
        .map((row, index) => ({ row, index }))
        .sort((left, right) => compareCells(left.row.cells[column], right.row.cells[column], direction) || left.index - right.index)
        .map(({ row }) => row);
      if (sorted.some((row, index) => row !== current[index])) body.append(...sorted);
    }
  }

  function enhanceTable(table) {
    if (table.dataset.stockscannerSortingReady !== undefined) return;
    if (table.querySelector(".sort-button, [data-sort-column]")) {
      table.dataset.stockscannerSortingReady = "custom";
      return;
    }
    const headers = [...table.querySelectorAll("thead th")];
    if (!headers.length) return;
    table.dataset.stockscannerSortingReady = "";
    headers.forEach((header, column) => {
      if (header.classList.contains("no-sort")) return;
      header.setAttribute("aria-sort", "none");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "stockscanner-sort-button";
      button.title = `Sort by ${header.textContent.trim()}`;
      button.append(...header.childNodes);
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        const ascending = table.dataset.stockscannerSortColumn !== String(column)
          || table.dataset.stockscannerSortDirection !== "ascending";
        headers.forEach((item) => item.setAttribute("aria-sort", "none"));
        const direction = ascending ? "ascending" : "descending";
        header.setAttribute("aria-sort", direction);
        table.dataset.stockscannerSortColumn = String(column);
        table.dataset.stockscannerSortDirection = direction;
        button.title = `Sorted ${direction}. Click to reverse.`;
        applySort(table);
      });
      header.append(button);
    });
  }

  document.querySelectorAll("table").forEach(enhanceTable);
  new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      const table = mutation.target.closest?.("table");
      if (table?.dataset.stockscannerSortingReady === "") applySort(table);
      for (const node of mutation.addedNodes) {
        if (!(node instanceof Element)) continue;
        if (node.matches("table")) enhanceTable(node);
        node.querySelectorAll?.("table").forEach(enhanceTable);
      }
    }
  }).observe(document.body, { childList: true, subtree: true });
}

async function protectPage() {
  const { data, error } = await supabase.auth.getUser();

  if (error || !data.user) {
    window.location.replace(loginUrl());
    return;
  }

  const { data: access, error: accessError } = await supabase
    .from("user_access")
    .select("status")
    .eq("user_id", data.user.id)
    .maybeSingle();

  if (accessError || access?.status !== "approved") {
    await supabase.auth.signOut({ scope: "local" });
    window.location.replace(`${APP_ROOT}login.html?approval=pending`);
    return;
  }

  const isAdmin = (data.user.email || "").toLowerCase() === ADMIN_EMAIL;
  if (document.documentElement.hasAttribute("data-admin-only") && !isAdmin) {
    window.location.replace(`${APP_ROOT}index.html`);
    return;
  }

  installPersonalExceptionApi(data.user);
  installPersonalBoughtApi(data.user);
  await applyPersonalTopTwentyFilters(data.user).catch((filterError) => {
    console.warn("Could not apply the personal Top 20 filters.", filterError);
  });
  addNavigationDrawer(data.user);
  reorderTechnicalAnalysisColumns();
  installReportStockFilters();
  installSharedTableSorting();
  showPage();
  await recordActivity(data.user, "page_view").catch(() => {});
  window.setInterval(
    () => updatePresence(data.user).catch(() => {}),
    5 * 60 * 1000,
  );
}

supabase.auth.onAuthStateChange((event) => {
  if (event === "SIGNED_OUT") {
    window.location.replace(`${APP_ROOT}login.html`);
  }
});

protectPage().catch(() => window.location.replace(loginUrl()));
