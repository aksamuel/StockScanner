// DOM wiring for pip-modules.html: connect to a PIP API, list the saved holdings and run one analysis module per click.
// The page only reads. It never calls the import, sync, saving-analysis or approval routes and never places orders.
import { PIP_DEFAULT_API_URL, normalizePipApiUrl, pipApiErrorMessage, pluralize } from "./pip-shared.js";
import {
  CONFIDENCE_NOTE,
  HOLDING_COLUMNS,
  PIP_MODULES,
  PIP_MODULE_FIELDS,
  buildModuleRequest,
  describeHolding,
  describeHoldingsFlags,
  describeHoldingsSummary,
  describeHoldingsTotals,
  describeModuleResult,
  describePortfolio,
  fieldInputId,
  fieldKey,
  filterHoldings,
  holdingCells,
  holdingInputHints,
  parseHoldingsResponse,
  parsePortfolioList,
} from "./pip-modules-core.js";

const API_URL_KEY = "stockscanner-pip-api-url";
const PORTFOLIO_KEY = "stockscanner-pip-module-portfolio";
const REQUEST_TIMEOUT_MS = 90000;
const CONNECT_LABEL = "Connect and load portfolios";
const WAKE_HINT = "A free Render service can take about a minute to wake up.";
const TIMEOUT_MESSAGE = `The PIP API did not answer within ${REQUEST_TIMEOUT_MS / 1000} seconds. ${WAKE_HINT} Try again.`;

function messageOf(error) {
  return typeof error?.message === "string" && error.message ? error.message : "Something went wrong. Try again.";
}

function healthProblem(health) {
  if (health?.service !== "pip") {
    return "That address did not answer like a PIP API. Check the URL.";
  }
  if (health.positions_list !== 1 || health.module_runner !== 1) {
    return "This PIP API is out of date: it cannot list holdings or run modules yet. Deploy the latest version and try again.";
  }
  return "";
}

function advanceNote(portfolioCount, foundHoldings, skipped) {
  if (portfolioCount < 2) return "";
  if (!foundHoldings) return `None of your ${portfolioCount} portfolios has saved holdings.`;
  if (!skipped) return "";
  return `Showing the newest portfolio that has holdings; ${pluralize(skipped, "newer portfolio")} ${skipped === 1 ? "is" : "are"} empty.`;
}

function startModulePage() {
  const apiUrlInput = document.querySelector("#moduleApiUrl");
  const connectButton = document.querySelector("#moduleConnect");
  const connectStatus = document.querySelector("#moduleConnectStatus");
  const runSection = document.querySelector("#moduleRunSection");
  const selectedHeading = document.querySelector("#moduleSelected");
  const selectedFacts = document.querySelector("#moduleSelectedFacts");
  const hintList = document.querySelector("#moduleHints");
  const inputsDetails = document.querySelector("#moduleInputs");
  const inputGroups = document.querySelector("#moduleInputGroups");
  const confidenceNote = document.querySelector("#moduleConfidenceNote");
  const buttonBox = document.querySelector("#moduleButtons");
  const runStatus = document.querySelector("#moduleRunStatus");
  const resultBox = document.querySelector("#moduleResult");
  const portfolioSection = document.querySelector("#modulePortfolioSection");
  const portfolioSelect = document.querySelector("#modulePortfolio");
  const filterInput = document.querySelector("#moduleFilter");
  const reloadButton = document.querySelector("#moduleReload");
  const holdingsStatus = document.querySelector("#moduleHoldingsStatus");
  const totalsList = document.querySelector("#moduleTotals");
  const flagsList = document.querySelector("#moduleFlags");
  const notesList = document.querySelector("#moduleNotes");
  const filterStatus = document.querySelector("#moduleFilterStatus");
  const headRow = document.querySelector("#moduleHeadRow");
  const holdingsBody = document.querySelector("#moduleHoldingsBody");

  const session = { base: "", portfolios: [], portfolio: null, overview: null, selected: null };
  const inputByKey = new Map();
  const moduleButtons = [];
  let connectToken = 0;
  let loadToken = 0;
  let runToken = 0;
  let running = false;
  let pendingOrigin = "";
  let authHandled = false;

  function readStored(key) {
    try {
      return localStorage.getItem(key) ?? "";
    } catch {
      return "";
    }
  }

  function writeStored(key, value) {
    try {
      localStorage.setItem(key, value);
    } catch {
      // Storage can be blocked (for example in private windows); the page still works without it.
    }
  }

  function make(tag, text = "", className = "") {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  }

  function makeList(items, className = "") {
    const list = make("ul", "", className);
    list.append(...items.map((item) => make("li", item)));
    return list;
  }

  function fillList(list, items) {
    list.replaceChildren(...items.map((item) => make("li", item)));
    list.hidden = items.length === 0;
  }

  function setStatus(node, message, { error = false, base = "subtle" } = {}) {
    node.textContent = message;
    node.className = error ? "error" : base;
  }

  // ---- Talking to the API ---------------------------------------------------------------------

  async function accessToken() {
    const auth = window.stockscannerPipAuth;
    if (typeof auth?.getAccessToken !== "function") {
      throw new Error("Sign-in is not ready. Reload the page after signing in.");
    }
    let token;
    try {
      token = await auth.getAccessToken();
    } catch (error) {
      throw new Error(messageOf(error));
    }
    if (typeof token !== "string" || !token) throw new Error("Your sign-in has expired. Sign in again.");
    return token;
  }

  // `auth: false` is for the public health check, which must never receive the sign-in token.
  async function apiRequest(base, path, { method = "GET", body, auth = true } = {}) {
    const headers = { Accept: "application/json" };
    if (auth) headers.Authorization = `Bearer ${await accessToken()}`;
    if (body !== undefined) headers["Content-Type"] = "application/json";
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    let response;
    let payload = null;
    let readable = false;
    try {
      response = await fetch(`${base}${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
        credentials: "omit",
        cache: "no-store",
      });
      payload = await response.json();
      readable = true;
    } catch {
      if (controller.signal.aborted) throw new Error(TIMEOUT_MESSAGE);
      if (!response) {
        const origin = window.location?.origin ?? "this page";
        throw new Error(`Could not reach the PIP API. Check the address and your connection, and that the service allows requests from ${origin} (set PIP_CORS_ORIGINS on the service).`);
      }
    } finally {
      clearTimeout(timer);
    }
    if (!response.ok) {
      if (!readable && [502, 503, 504].includes(response.status)) {
        throw new Error(`The PIP API is not ready (HTTP ${response.status}). ${WAKE_HINT} Try again shortly.`);
      }
      throw new Error(pipApiErrorMessage(readable ? payload : null, response.status));
    }
    if (!readable) throw new Error("The PIP API answered with something that is not valid JSON.");
    return payload;
  }

  // ---- Building the static parts of the page --------------------------------------------------

  function buildHeader() {
    const cells = HOLDING_COLUMNS.map((column) => {
      const cell = make("th", column.label, column.numeric ? "numeric" : "");
      cell.setAttribute("scope", "col");
      return cell;
    });
    const action = make("th", "Modules");
    action.setAttribute("scope", "col");
    headRow.replaceChildren(...cells, action);
  }

  function buildInput(field) {
    const input = make(field.type === "candidates" ? "textarea" : "input");
    input.id = fieldInputId(field);
    input.value = field.value ?? "";
    input.setAttribute("autocomplete", "off");
    if (field.type === "candidates") {
      input.setAttribute("rows", "2");
      input.setAttribute("spellcheck", "false");
    } else {
      input.type = "text";
      if (field.type === "date") input.setAttribute("placeholder", "YYYY-MM-DD");
      if (field.positive || (field.min ?? -1) >= 0) input.setAttribute("inputmode", "decimal");
    }
    if (field.placeholder) input.setAttribute("placeholder", field.placeholder);
    return input;
  }

  function buildInputs() {
    const groups = new Map();
    for (const field of PIP_MODULE_FIELDS) {
      if (!groups.has(field.group)) groups.set(field.group, []);
      groups.get(field.group).push(field);
    }
    const sets = [];
    for (const [group, fields] of groups) {
      const set = make("fieldset");
      const grid = make("div", "", "input-grid");
      for (const field of fields) {
        const input = buildInput(field);
        const label = make("label", field.label);
        label.setAttribute("for", input.id);
        const help = make("small", field.help);
        help.id = `${input.id}-help`;
        input.setAttribute("aria-describedby", help.id);
        const box = make("div", "", "field");
        box.append(label, input, help);
        grid.append(box);
        inputByKey.set(fieldKey(field), input);
      }
      set.append(make("legend", group), grid);
      sets.push(set);
    }
    inputGroups.replaceChildren(...sets);
  }

  function buildModuleButtons() {
    for (const module of PIP_MODULES) {
      const button = make("button", module.label);
      button.type = "button";
      const needs = make("small", module.needs);
      needs.id = `moduleNeeds-${module.id}`;
      button.setAttribute("aria-describedby", needs.id);
      button.addEventListener("click", () => runModule(module));
      const box = make("div", "", "module-action");
      box.append(button, needs);
      buttonBox.append(box);
      moduleButtons.push(button);
    }
  }

  function updateButtons() {
    for (const button of moduleButtons) button.disabled = running;
  }

  // ---- Connecting, portfolios and holdings ----------------------------------------------------

  function setConnecting(busy) {
    connectButton.disabled = busy;
    connectButton.textContent = busy ? "Connecting…" : CONNECT_LABEL;
  }

  function clearHoldings() {
    runToken += 1;
    running = false;
    session.portfolio = null;
    session.overview = null;
    session.selected = null;
    holdingsBody.replaceChildren();
    fillList(totalsList, []);
    fillList(flagsList, []);
    fillList(notesList, []);
    setStatus(holdingsStatus, "");
    setStatus(filterStatus, "");
    runSection.hidden = true;
    resultBox.replaceChildren();
    resultBox.hidden = true;
    setStatus(runStatus, "", { base: "" });
    updateButtons();
  }

  function resetConnection() {
    loadToken += 1;
    session.base = "";
    session.portfolios = [];
    portfolioSelect.replaceChildren();
    portfolioSection.hidden = true;
    clearHoldings();
  }

  function holdingRow(holding) {
    const row = make("tr", "", session.selected?.symbol === holding.symbol ? "selected" : "");
    holdingCells(holding).forEach((text, index) => {
      const column = HOLDING_COLUMNS[index];
      row.append(make("td", text, index === 0 ? "symbol" : column?.numeric ? "numeric" : ""));
    });
    const button = make("button", "Run modules", "secondary");
    button.type = "button";
    button.setAttribute("aria-label", `Run modules for ${holding.symbol}`);
    button.addEventListener("click", () => selectHolding(holding));
    const action = make("td");
    action.append(button);
    row.append(action);
    return row;
  }

  function emptyRow(message) {
    const cell = make("td", message, "empty");
    cell.setAttribute("colspan", String(HOLDING_COLUMNS.length + 1));
    const row = make("tr");
    row.append(cell);
    return row;
  }

  function renderRows() {
    const overview = session.overview;
    if (!overview) return;
    const shown = filterHoldings(overview.holdings, filterInput.value);
    const rows = shown.length
      ? shown.map(holdingRow)
      : [emptyRow(overview.holdings.length ? "No holding matches this filter." : "No holdings to show.")];
    holdingsBody.replaceChildren(...rows);
    const filtering = overview.holdings.length > 0 && filterInput.value.trim() !== "";
    setStatus(filterStatus, filtering ? `Showing ${shown.length} of ${pluralize(overview.holdings.length, "holding")}.` : "");
  }

  function showPortfolio(portfolio, overview, note) {
    session.portfolio = portfolio;
    session.overview = overview;
    portfolioSelect.value = portfolio.id;
    writeStored(PORTFOLIO_KEY, portfolio.id);
    setStatus(holdingsStatus, [describeHoldingsSummary(overview), note].filter(Boolean).join(" "));
    fillList(totalsList, describeHoldingsTotals(overview.totals));
    fillList(flagsList, describeHoldingsFlags(overview.flags));
    fillList(notesList, overview.notes);
    renderRows();
  }

  // With `advance`, portfolios are tried newest first until one has holdings, because a newer import can be empty.
  async function loadPortfolio(portfolioId, { advance = false } = {}) {
    const order = advance ? session.portfolios : session.portfolios.filter((item) => item.id === portfolioId);
    if (!order.length) return;
    const token = ++loadToken;
    const base = session.base;
    clearHoldings();
    let first = null;
    let skipped = 0;
    for (const portfolio of order) {
      portfolioSelect.value = portfolio.id;
      setStatus(holdingsStatus, `Loading the holdings of ${describePortfolio(portfolio)}…`);
      let overview;
      try {
        const path = `/api/pip/portfolios/${encodeURIComponent(portfolio.id)}/positions`;
        overview = parseHoldingsResponse(await apiRequest(base, path));
      } catch (error) {
        if (token === loadToken) setStatus(holdingsStatus, messageOf(error), { error: true });
        return;
      }
      if (token !== loadToken) return;
      first ??= { portfolio, overview };
      if (overview.holdings.length) {
        showPortfolio(portfolio, overview, advanceNote(order.length, true, skipped));
        return;
      }
      skipped += 1;
    }
    showPortfolio(first.portfolio, first.overview, advanceNote(order.length, false, skipped));
  }

  async function connect() {
    const parsed = normalizePipApiUrl(apiUrlInput.value);
    if (!parsed.ok) {
      setStatus(connectStatus, parsed.error, { error: true });
      return;
    }
    if (!parsed.isDefault && !parsed.isLocal && pendingOrigin !== parsed.origin) {
      pendingOrigin = parsed.origin;
      setStatus(connectStatus, `${parsed.origin} is not the default PIP service. Connecting sends your sign-in token to it. Select Connect again only if you deployed or trust that service.`, { error: true });
      return;
    }
    pendingOrigin = "";
    const token = ++connectToken;
    resetConnection();
    setConnecting(true);
    setStatus(connectStatus, `Connecting to ${parsed.url}… The first request can take about a minute while a free service wakes up.`);
    try {
      const problem = healthProblem(await apiRequest(parsed.url, "/healthz", { auth: false }));
      if (token !== connectToken) return;
      if (problem) throw new Error(problem);
      setStatus(connectStatus, "Loading your portfolios…");
      const portfolios = parsePortfolioList(await apiRequest(parsed.url, "/api/pip/portfolios"));
      if (token !== connectToken) return;
      session.base = parsed.url;
      session.portfolios = portfolios;
      writeStored(API_URL_KEY, parsed.url);
      if (!portfolios.length) {
        setStatus(connectStatus, `Connected to ${parsed.url}, but you have no portfolios yet. Import positions or sync IBKR Flex in the PIP workbench first.`);
        return;
      }
      setStatus(connectStatus, `Connected to ${parsed.url}. ${pluralize(portfolios.length, "portfolio")} found.`);
      portfolioSelect.replaceChildren(...portfolios.map((portfolio) => {
        const option = make("option", describePortfolio(portfolio));
        option.value = portfolio.id;
        return option;
      }));
      portfolioSection.hidden = false;
      const remembered = portfolios.find((item) => item.id === readStored(PORTFOLIO_KEY));
      await loadPortfolio((remembered ?? portfolios[0]).id, { advance: !remembered });
    } catch (error) {
      if (token === connectToken) setStatus(connectStatus, messageOf(error), { error: true });
    } finally {
      if (token === connectToken) setConnecting(false);
    }
  }

  // ---- Running a module -----------------------------------------------------------------------

  function selectHolding(holding) {
    const changed = session.selected?.symbol !== holding.symbol;
    if (changed) {
      runToken += 1;
      running = false;
      session.selected = holding;
      for (const field of PIP_MODULE_FIELDS) {
        if (field.scope === "holding") inputByKey.get(fieldKey(field)).value = field.value ?? "";
      }
      selectedHeading.textContent = `Run modules for ${holding.symbol}`;
      selectedFacts.textContent = describeHolding(holding);
      const hints = holdingInputHints(holding);
      fillList(hintList, hints);
      if (hints.length) inputsDetails.open = true;
      resultBox.replaceChildren();
      resultBox.hidden = true;
      setStatus(runStatus, "", { base: "" });
      updateButtons();
      renderRows();
    }
    runSection.hidden = false;
    runSection.scrollIntoView?.({ block: "start" });
    selectedHeading.focus?.({ preventScroll: true });
  }

  function readInputs() {
    return Object.fromEntries([...inputByKey].map(([key, input]) => [key, input.value]));
  }

  function showResult(module, holding, response) {
    const view = describeModuleResult(module.id, response);
    const parts = [make("h3", `${view.title} · ${holding.symbol}`), make("p", view.headline, "headline")];
    if (view.rows.length) {
      const facts = make("dl", "", "facts");
      for (const [label, value] of view.rows) facts.append(make("dt", label), make("dd", value));
      parts.push(facts);
    }
    if (view.details.length) parts.push(makeList(view.details));
    if (view.hints.length) {
      const hints = make("div", "", "hints");
      hints.append(make("strong", "To get a fuller answer"), makeList(view.hints));
      parts.push(hints);
    }
    if (view.caveats.length) parts.push(makeList(view.caveats, "caveats"));
    if (view.footer) parts.push(make("p", view.footer, "result-footer"));
    resultBox.className = view.unexpected ? "result unexpected" : "result";
    resultBox.replaceChildren(...parts);
    resultBox.hidden = false;
    setStatus(
      runStatus,
      view.unexpected ? `${view.title} returned an unexpected response.` : `${view.title} finished for ${holding.symbol}.`,
      { error: view.unexpected, base: "" },
    );
    resultBox.scrollIntoView?.({ block: "nearest" });
  }

  async function runModule(module) {
    const holding = session.selected;
    if (running || !holding) return;
    let body;
    try {
      body = buildModuleRequest(holding.symbol, readInputs());
    } catch (error) {
      inputsDetails.open = true;
      setStatus(runStatus, messageOf(error), { error: true, base: "" });
      return;
    }
    const token = ++runToken;
    const base = session.base;
    const path = `/api/pip/portfolios/${encodeURIComponent(session.portfolio.id)}/modules/${module.id}`;
    running = true;
    updateButtons();
    resultBox.hidden = true;
    setStatus(runStatus, `Running ${module.label} for ${holding.symbol}…`, { base: "" });
    try {
      const response = await apiRequest(base, path, { method: "POST", body });
      if (token === runToken) showResult(module, holding, response);
    } catch (error) {
      if (token === runToken) setStatus(runStatus, messageOf(error), { error: true, base: "" });
    } finally {
      if (token === runToken) {
        running = false;
        updateButtons();
      }
    }
  }

  // ---- Start-up -------------------------------------------------------------------------------

  function onAuthReady() {
    if (authHandled) return;
    authHandled = true;
    connectButton.disabled = false;
    const parsed = normalizePipApiUrl(apiUrlInput.value);
    if (parsed.ok && parsed.isDefault) {
      connect();
    } else {
      setStatus(connectStatus, parsed.ok ? `Select Connect to use ${parsed.origin}.` : parsed.error, { error: !parsed.ok });
    }
  }

  apiUrlInput.value = readStored(API_URL_KEY) || PIP_DEFAULT_API_URL;
  confidenceNote.textContent = CONFIDENCE_NOTE;
  buildHeader();
  buildInputs();
  buildModuleButtons();
  connectButton.addEventListener("click", () => connect());
  apiUrlInput.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" || connectButton.disabled) return;
    event.preventDefault();
    connect();
  });
  portfolioSelect.addEventListener("change", () => loadPortfolio(portfolioSelect.value));
  reloadButton.addEventListener("click", () => loadPortfolio(portfolioSelect.value));
  filterInput.addEventListener("input", renderRows);
  window.addEventListener("stockscanner-pip-auth-ready", onAuthReady, { once: true });
  if (window.stockscannerPipAuth) onAuthReady();
}

if (typeof document !== "undefined") startModulePage();
