import { portfolioImportPreviewFromCsv, portfolioRowsFromCsv } from "./portfolio-analysis.js";

export const PIP_CPS_WEIGHTS = Object.freeze({
  tsr: 40,
  relative_performance: 20,
  dividend_growth: 15,
  earnings_growth: 15,
  analyst_revisions: 10,
});

export const PIP_SELL_SCORE_WEIGHTS = Object.freeze({
  tsr: 20,
  relative_performance: 20,
  revisions: 20,
  dividend_quality: 15,
  technical_health: 15,
  earnings_growth: 10,
  opportunity_cost: 15,
});

export const PIP_DEFAULT_API_URL = "https://stockscanner-pip-api.onrender.com";

export const PIP_APPROVAL_TRANSITIONS = Object.freeze({
  draft: ["under_review", "cancelled", "expired"],
  proposed: ["under_review", "cancelled", "expired"],
  under_review: ["approved", "rejected", "escalated", "cancelled", "expired"],
  approved: ["submitted", "escalated", "cancelled"],
  rejected: [],
  expired: [],
  submitted: [],
  cancelled: [],
  escalated: ["under_review", "approved", "rejected", "cancelled", "expired"],
});

export function transitionPipApproval(currentStatus, nextStatus, actor, reason, now = new Date()) {
  if (!PIP_APPROVAL_TRANSITIONS[currentStatus]?.includes(nextStatus)) {
    throw new Error(`Cannot transition PIP approval from ${currentStatus} to ${nextStatus}.`);
  }
  const normalizedActor = String(actor || "").trim();
  const normalizedReason = String(reason || "").trim();
  if (!normalizedActor || !normalizedReason) {
    throw new Error("PIP approval transition requires an actor and a reason.");
  }
  return {
    status: nextStatus,
    event: {
      from_status: currentStatus,
      to_status: nextStatus,
      actor: normalizedActor,
      reason: normalizedReason,
      created_at: new Date(now).toISOString(),
    },
  };
}

export function calculatePipScore(components, weights) {
  const entries = Object.entries(weights);
  const totalWeight = entries.reduce((sum, [, weight]) => sum + weight, 0);
  const available = [];
  const reasons = [];

  for (const [name, weight] of entries) {
    const value = components[name];
    if (value === null || value === undefined || value === "") {
      reasons.push(`${name.replaceAll("_", " ")} data is missing.`);
      continue;
    }
    const score = Number(value);
    if (!Number.isFinite(score)) {
      reasons.push(`${name.replaceAll("_", " ")} data is invalid.`);
      continue;
    }
    available.push([Math.max(0, Math.min(100, score)), weight]);
  }

  const availableWeight = available.reduce((sum, [, weight]) => sum + weight, 0);
  return {
    score: availableWeight
      ? available.reduce((sum, [score, weight]) => sum + score * weight, 0) / availableWeight
      : null,
    confidence: totalWeight ? availableWeight / totalWeight : 0,
    reasons,
  };
}

export { portfolioImportPreviewFromCsv, portfolioRowsFromCsv };

if (typeof document !== "undefined") {
  const scoreFields = [
    ["tsr", "Total shareholder return"],
    ["relative_performance", "Relative performance"],
    ["dividend_growth", "Dividend growth"],
    ["earnings_growth", "Earnings growth"],
    ["analyst_revisions", "Analyst revisions (CPS)"],
    ["revisions", "Analyst revisions (Sell Score)"],
    ["dividend_quality", "Dividend quality"],
    ["technical_health", "Technical health"],
    ["opportunity_cost", "Opportunity cost"],
  ];
  const inputElements = new Map();
  const sampleValues = {
    tsr: 70,
    relative_performance: 55,
    dividend_growth: 62,
    earnings_growth: 68,
    analyst_revisions: 58,
    revisions: 58,
    dividend_quality: 75,
    technical_health: 64,
    opportunity_cost: 45,
  };
  const transitions = document.querySelectorAll("[data-transition]");
  const apiUrlInput = document.querySelector("#pipApiUrl");
  const portfolioSelect = document.querySelector("#portfolioSelect");
  const recommendationSelect = document.querySelector("#recommendationSelect");
  const apiStatus = document.querySelector("#pipApiStatus");
  const flexStatus = document.querySelector("#flexStatus");
  const flexConnectionList = document.querySelector("#flexConnectionList");
  let csvText = null;
  let portfolios = [];
  let apiConnected = false;
  let selectedRecommendation = null;
  let researchRequestId = 0;

  function renderScore(result, valueId, confidenceId, reasonsId) {
    document.querySelector(valueId).textContent = result.score === null ? "Unavailable" : `${result.score.toFixed(1)} / 100`;
    document.querySelector(confidenceId).textContent = `Confidence: ${(result.confidence * 100).toFixed(0)}%`;
    document.querySelector(reasonsId).textContent = result.reasons.length
      ? `Missing or invalid: ${result.reasons.join(" ")}`
      : "All configured components are present.";
  }

  function updateScores() {
    const components = Object.fromEntries([...inputElements].map(([name, input]) => [
      name,
      input.value === "" ? null : input.value,
    ]));
    renderScore(calculatePipScore(components, PIP_CPS_WEIGHTS), "#cpsValue", "#cpsConfidence", "#cpsReasons");
    renderScore(calculatePipScore(components, PIP_SELL_SCORE_WEIGHTS), "#sellScoreValue", "#sellScoreConfidence", "#sellScoreReasons");
  }

  for (const [name, labelText] of scoreFields) {
    const label = document.createElement("label");
    label.textContent = labelText;
    const input = document.createElement("input");
    input.type = "number";
    input.min = "0";
    input.max = "100";
    input.step = "any";
    input.inputMode = "decimal";
    input.setAttribute("aria-label", `${labelText} component score, 0 to 100`);
    input.addEventListener("input", updateScores);
    label.append(input);
    document.querySelector("#scoreInputs").append(label);
    inputElements.set(name, input);
  }

  function setBusy(button, busy, label) {
    if (busy) {
      button.dataset.originalText = button.textContent;
      button.textContent = label;
    } else if (button.dataset.originalText) {
      button.textContent = button.dataset.originalText;
      delete button.dataset.originalText;
    }
    button.disabled = busy;
  }

  function apiBase() {
    const url = new URL(apiUrlInput.value.trim());
    if (url.protocol !== "https:" && !["localhost", "127.0.0.1"].includes(url.hostname)) {
      throw new Error("Use HTTPS for the PIP API URL.");
    }
    return url.href.replace(/\/+$/, "");
  }

  async function apiRequest(path, options = {}) {
    if (!window.stockscannerPipAuth?.getAccessToken) {
      throw new Error("Supabase authentication is not ready. Reload the page after signing in.");
    }
    const token = await window.stockscannerPipAuth.getAccessToken();
    const { contentType, ...requestOptions } = options;
    const response = await fetch(`${apiBase()}${path}`, {
      ...requestOptions,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(options.body ? { "Content-Type": contentType || "application/json" } : {}),
        ...options.headers,
      },
    });
    let payload;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    if (!response.ok) {
      throw new Error(payload?.detail || `PIP API request failed (${response.status}).`);
    }
    return payload;
  }

  function selectedPortfolio() {
    const id = portfolioSelect.value;
    if (!id || !portfolios.some((portfolio) => portfolio.id === id)) {
      throw new Error("Select a portfolio first.");
    }
    return id;
  }

  function optionalNumber(id, label, { min = null, max = null } = {}) {
    const raw = document.querySelector(id).value.trim();
    if (raw === "") return null;
    const value = Number(raw);
    if (!Number.isFinite(value)) throw new Error(`${label} must be a number.`);
    if (min !== null && value < min) throw new Error(`${label} must be at least ${min}.`);
    if (max !== null && value > max) throw new Error(`${label} must be no more than ${max}.`);
    return value;
  }

  function readPeerScores() {
    const raw = document.querySelector("#pipPeerScores").value.trim();
    if (!raw) return [];
    return raw.split(",").map((entry) => {
      const [symbolValue, scoreValue, ...extra] = entry.split(":");
      const symbol = symbolValue.trim().toUpperCase();
      const score = Number(scoreValue);
      if (extra.length || !/^[A-Z0-9][A-Z0-9.-]{0,29}$/.test(symbol)
        || !Number.isFinite(score) || score < 0 || score > 100) {
        throw new Error(`Invalid replacement candidate: ${entry.trim()}. Use SYMBOL:score from 0 to 100.`);
      }
      return { symbol, score };
    });
  }

  function updateImportEnabled() {
    document.querySelector("#importCsv").disabled = !apiConnected || !csvText || !portfolioSelect.value;
  }

  function updateResearchEnabled() {
    const symbol = document.querySelector("#analysisSymbol").value.trim();
    document.querySelector("#loadResearch").disabled = !apiConnected
      || !portfolioSelect.value
      || !/^[A-Z0-9][A-Z0-9.-]{0,29}$/i.test(symbol);
  }

  function resetAnalysisInputs() {
    researchRequestId += 1;
    const researchButton = document.querySelector("#loadResearch");
    if (researchButton.dataset.originalText) setBusy(researchButton, false);
    for (const input of inputElements.values()) input.value = "";
    for (const id of [
      "#pipEntryDate",
      "#pipCostBasis",
      "#pipMarketValue",
      "#pipMarketPrice",
      "#pipDividendsReceived",
      "#pipPayoutRatio",
      "#pipDividendGrowth",
      "#pipDividendConsistency",
      "#pipEarningsGrowth",
      "#pipRevenueGrowth",
      "#pipTargetPrice",
      "#pipTargetUpside",
      "#pipForwardRevisions",
      "#pipPeerScores",
    ]) {
      document.querySelector(id).value = "";
    }
    document.querySelector("#researchResult").hidden = true;
    document.querySelector("#analysisResult").hidden = true;
    updateScores();
  }

  function updateFlexControls() {
    const ready = apiConnected && Boolean(portfolioSelect.value);
    document.querySelector("#saveFlexConnection").disabled = !ready;
    flexConnectionList.querySelectorAll("button").forEach((button) => {
      button.disabled = !ready || Boolean(button.dataset.originalText);
    });
  }

  function renderFlexConnections(rows) {
    flexConnectionList.replaceChildren();
    if (!rows.length) {
      const empty = document.createElement("p");
      empty.className = "empty-state";
      empty.textContent = "No saved Flex connections for this portfolio.";
      flexConnectionList.append(empty);
      updateFlexControls();
      return;
    }

    for (const connection of rows) {
      const item = document.createElement("article");
      item.className = "flex-connection-item";
      const name = document.createElement("strong");
      name.textContent = connection.connection_name || "IBKR Flex connection";
      const lastSync = document.createElement("p");
      lastSync.className = "subtle";
      const syncDate = connection.last_synced_at
        ? new Date(connection.last_synced_at)
        : null;
      lastSync.textContent = syncDate && Number.isFinite(syncDate.getTime())
        ? `Last synced ${syncDate.toLocaleString()}.`
        : "Never synced.";
      const actions = document.createElement("div");
      actions.className = "button-row";

      const syncButton = document.createElement("button");
      syncButton.type = "button";
      syncButton.textContent = "Sync statement";
      syncButton.addEventListener("click", async () => {
        setBusy(syncButton, true, "Syncing…");
        flexStatus.textContent = `Requesting a read-only Flex statement for ${name.textContent}…`;
        try {
          const result = await apiRequest(
            `/api/pip/portfolios/${encodeURIComponent(portfolioSelect.value)}/ibkr-flex-connections/${encodeURIComponent(connection.id)}/sync`,
            { method: "POST" },
          );
          await loadFlexConnections();
          const counts = result.counts || {};
          const accountSummary = (result.accounts || [])
            .map((account) => `${account.masked_account_id || "masked account"} (${account.currency || "currency unavailable"})`)
            .join(", ");
          const warning = result.warnings?.length ? ` ${result.warnings.join(" ")}` : "";
          flexStatus.textContent = `Synced ${counts.positions || 0} positions, ${counts.transactions || 0} transactions, ${counts.dividends || 0} dividends, and ${counts.accounts || 0} masked accounts${accountSummary ? `: ${accountSummary}` : ""}.${warning}`;
        } catch (error) {
          flexStatus.textContent = error.message || "IBKR Flex sync failed.";
        } finally {
          setBusy(syncButton, false);
          updateFlexControls();
        }
      });

      const disconnectButton = document.createElement("button");
      disconnectButton.type = "button";
      disconnectButton.className = "secondary";
      disconnectButton.textContent = "Remove connection";
      disconnectButton.addEventListener("click", async () => {
        if (!window.confirm(`Remove "${connection.connection_name}" and delete its saved Vault credentials?`)) return;
        setBusy(disconnectButton, true, "Removing…");
        flexStatus.textContent = `Removing ${name.textContent}…`;
        try {
          await apiRequest(
            `/api/pip/portfolios/${encodeURIComponent(portfolioSelect.value)}/ibkr-flex-connections/${encodeURIComponent(connection.id)}`,
            { method: "DELETE" },
          );
          await loadFlexConnections();
          flexStatus.textContent = `Removed ${name.textContent} and deleted its saved credentials.`;
        } catch (error) {
          flexStatus.textContent = error.message || "Could not remove the Flex connection.";
        } finally {
          setBusy(disconnectButton, false);
          updateFlexControls();
        }
      });

      actions.append(syncButton, disconnectButton);
      item.append(name, lastSync, actions);
      flexConnectionList.append(item);
    }
    updateFlexControls();
  }

  async function loadFlexConnections() {
    const portfolioId = portfolioSelect.value;
    if (!portfolioId) {
      renderFlexConnections([]);
      flexStatus.textContent = "Select a portfolio to manage Flex connections.";
      return;
    }
    flexStatus.textContent = "Loading saved Flex connections…";
    try {
      const rows = await apiRequest(
        `/api/pip/portfolios/${encodeURIComponent(portfolioId)}/ibkr-flex-connections`,
      );
      if (portfolioSelect.value !== portfolioId) return;
      if (!Array.isArray(rows)) throw new Error("The PIP API returned an invalid Flex connection list.");
      renderFlexConnections(rows);
      flexStatus.textContent = rows.length
        ? `Loaded ${rows.length} Flex connection${rows.length === 1 ? "" : "s"}.`
        : "No saved Flex connections. Add one after the Vault migration and Edge Function are configured.";
    } catch (error) {
      if (portfolioSelect.value !== portfolioId) return;
      renderFlexConnections([]);
      flexStatus.textContent = error.message || "Could not load Flex connections.";
    }
  }

  function renderRecommendations(rows, selectId = null) {
    recommendationSelect.replaceChildren();
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = rows.length ? "Select a recommendation" : "No saved recommendations";
    recommendationSelect.append(placeholder);
    for (const row of rows) {
      const option = document.createElement("option");
      option.value = row.id;
      option.textContent = `${row.symbol} · ${row.recommendation} · ${row.status}`;
      option.dataset.status = row.status;
      recommendationSelect.append(option);
    }
    if (selectId && rows.some((row) => row.id === selectId)) {
      recommendationSelect.value = selectId;
    }
    selectedRecommendation = recommendationSelect.value || null;
    document.querySelector("#approvalStatus").textContent = recommendationSelect.selectedOptions[0]?.dataset.status || "Not selected";
    updateTransitionButtons();
  }

  async function loadRecommendations(selectId = null) {
    if (!portfolioSelect.value) {
      renderRecommendations([]);
      return;
    }
    const rows = await apiRequest(
      `/api/pip/portfolios/${encodeURIComponent(portfolioSelect.value)}/recommendations`,
    );
    renderRecommendations(rows, selectId);
    if (recommendationSelect.value) await loadApprovalEvents(recommendationSelect.value);
    else {
      document.querySelector("#approvalStatus").textContent = "Not selected";
      renderEvents([]);
    }
  }

  function renderEvents(events) {
    const list = document.querySelector("#approvalEvents");
    list.replaceChildren();
    if (!events.length) {
      const empty = document.createElement("li");
      empty.className = "empty-state";
      empty.textContent = "No approval transitions recorded.";
      list.append(empty);
      return;
    }
    for (const event of events) {
      const details = event.event_details || {};
      const item = document.createElement("li");
      item.textContent = `${details.from_status || "new"} → ${details.to_status || event.event_type} · ${details.actor || "system"} · ${details.reason || "No reason supplied"} · ${new Date(event.created_at).toLocaleString()}`;
      list.append(item);
    }
  }

  async function loadApprovalEvents(recommendationId) {
    const rows = await apiRequest(
      `/api/pip/recommendations/${encodeURIComponent(recommendationId)}/events`,
    );
    renderEvents(rows);
  }

  function updateTransitionButtons() {
    const status = recommendationSelect.selectedOptions[0]?.dataset.status;
    transitions.forEach((button) => {
      button.disabled = !apiConnected
        || !selectedRecommendation
        || !PIP_APPROVAL_TRANSITIONS[status]?.includes(button.dataset.transition);
    });
  }

  async function refreshPortfolios() {
    portfolios = await apiRequest("/api/pip/portfolios");
    const previous = portfolioSelect.value;
    portfolioSelect.replaceChildren();
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = portfolios.length ? "Select a portfolio" : "Create a portfolio first";
    portfolioSelect.append(placeholder);
    portfolios.forEach((portfolio) => {
      const option = document.createElement("option");
      option.value = portfolio.id;
      option.textContent = `${portfolio.name} (${portfolio.currency})`;
      portfolioSelect.append(option);
    });
    if (portfolios.some((portfolio) => portfolio.id === previous)) portfolioSelect.value = previous;
    if (portfolioSelect.value !== previous) resetAnalysisInputs();
    document.querySelector("#portfolioControls").hidden = false;
    updateImportEnabled();
    updateResearchEnabled();
    updateFlexControls();
    await Promise.all([loadRecommendations(), loadFlexConnections()]);
  }

  function showAnalysis(result) {
    const container = document.querySelector("#analysisResult");
    container.replaceChildren();
    const heading = document.createElement("strong");
    heading.textContent = `${result.recommendation.symbol} · ${result.recommendation.recommendation}`;
    const detail = document.createElement("p");
    detail.textContent = `CPS ${result.analysis.cps === null ? "unavailable" : result.analysis.cps.toFixed(1)} · Sell Score ${result.analysis.sell_score === null ? "unavailable" : result.analysis.sell_score.toFixed(1)} · data confidence ${(result.analysis.confidence * 100).toFixed(0)}%`;
    const reasons = document.createElement("p");
    reasons.textContent = result.analysis.rationale.join(" ");
    const modules = result.modules;
    const assessments = [
      `Lifecycle: ${modules.lifecycle.days_held === null ? "holding date unavailable" : `${modules.lifecycle.days_held} days held`}; total return ${modules.lifecycle.total_return_percent === null ? "unavailable" : `${modules.lifecycle.total_return_percent.toFixed(1)}%`}.`,
      `Dead money: ${modules.dead_money.is_dead_money === null ? "insufficient data" : modules.dead_money.is_dead_money ? "flagged for review" : "not flagged"} (${(modules.dead_money.confidence * 100).toFixed(0)}% input confidence).`,
      `Dividends: trailing 12-month income ${modules.dividends.trailing_twelve_month_income === null ? "unavailable" : modules.dividends.trailing_twelve_month_income.toFixed(2)}; yield ${modules.dividends.current_yield_pct === null ? "unavailable" : `${modules.dividends.current_yield_pct.toFixed(2)}%`}.`,
      `Growth: ${modules.growth.score === null ? "unavailable" : `${modules.growth.score.toFixed(1)} / 100`} (${(modules.growth.confidence * 100).toFixed(0)}% input confidence).`,
      `Forward-looking: ${modules.forward_looking.score === null ? "unavailable" : `${modules.forward_looking.score.toFixed(1)} / 100`} (${(modules.forward_looking.confidence * 100).toFixed(0)}% input confidence).`,
      `Opportunity cost: ${!modules.opportunity_cost.available
        ? modules.opportunity_cost.reasons.join(" ")
        : modules.opportunity_cost.items.length
          ? `${modules.opportunity_cost.items.length} alternatives; top is ${modules.opportunity_cost.items[0].alternative_symbol}`
          : "no stronger alternatives supplied"}.`,
      `Replacement candidates: ${result.recommendation.replacement_candidates.length ? result.recommendation.replacement_candidates.map((candidate) => `${candidate.symbol} (${candidate.score.toFixed(1)})`).join(", ") : "none qualified from supplied inputs"}.`,
    ];
    const assessmentText = document.createElement("p");
    assessmentText.textContent = assessments.join(" ");
    container.append(heading, detail, reasons, assessmentText);
    container.hidden = false;
  }

  async function connect() {
    const button = document.querySelector("#connectApi");
    setBusy(button, true, "Connecting…");
    apiStatus.textContent = "Checking API and loading your portfolios…";
    try {
      const base = apiBase();
      localStorage.setItem("stockscanner-pip-api-url", base);
      await apiRequest("/healthz");
      apiConnected = true;
      await refreshPortfolios();
      apiStatus.textContent = `Connected to ${base}. Your authenticated Supabase account is required for portfolio data.`;
      updateTransitionButtons();
    } catch (error) {
      apiConnected = false;
      apiStatus.textContent = error.message || "PIP API connection failed.";
      updateImportEnabled();
      updateResearchEnabled();
      updateTransitionButtons();
      updateFlexControls();
    } finally {
      setBusy(button, false);
      updateImportEnabled();
      updateFlexControls();
    }
  }

  apiUrlInput.value = localStorage.getItem("stockscanner-pip-api-url") || PIP_DEFAULT_API_URL;
  document.querySelector("#connectApi").addEventListener("click", connect);
  document.querySelector("#createPortfolio").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    setBusy(button, true, "Creating…");
    try {
      const created = await apiRequest("/api/pip/portfolios", {
        method: "POST",
        body: JSON.stringify({
          name: document.querySelector("#portfolioName").value,
          currency: document.querySelector("#portfolioCurrency").value,
        }),
      });
      await refreshPortfolios();
      if (portfolioSelect.value !== created.id) resetAnalysisInputs();
      portfolioSelect.value = created.id;
      await Promise.all([loadRecommendations(), loadFlexConnections()]);
      updateImportEnabled();
      updateResearchEnabled();
      updateFlexControls();
      apiStatus.textContent = `Created portfolio ${created.name}.`;
    } catch (error) {
      apiStatus.textContent = error.message || "Portfolio creation failed.";
    } finally {
      setBusy(button, false);
    }
  });

  document.querySelector("#saveFlexConnection").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const tokenInput = document.querySelector("#flexToken");
    const queryIdInput = document.querySelector("#flexQueryId");
    const name = document.querySelector("#flexConnectionName").value.trim();
    const token = tokenInput.value;
    const queryId = queryIdInput.value.trim();
    try {
      const portfolioId = selectedPortfolio();
      if (!name) throw new Error("Enter a name for this Flex connection.");
      if (!token || !queryId) throw new Error("Enter the IBKR Flex token and Query ID.");
      setBusy(button, true, "Saving encrypted credentials…");
      flexStatus.textContent = "Sending credentials to the authenticated API for encrypted Vault storage…";
      const connection = await apiRequest(
        `/api/pip/portfolios/${encodeURIComponent(portfolioId)}/ibkr-flex-connections`,
        {
          method: "POST",
          body: JSON.stringify({
            connection_name: name,
            token,
            query_id: queryId,
          }),
        },
      );
      await loadFlexConnections();
      flexStatus.textContent = `Saved ${connection.connection_name}. Sync is read-only and requires an XML Flex Query.`;
    } catch (error) {
      flexStatus.textContent = error.message || "Could not save the Flex connection.";
    } finally {
      tokenInput.value = "";
      queryIdInput.value = "";
      setBusy(button, false);
      updateFlexControls();
    }
  });

  document.querySelector("#loadSample").addEventListener("click", () => {
    renderScore(
      calculatePipScore(sampleValues, PIP_CPS_WEIGHTS),
      "#cpsValue",
      "#cpsConfidence",
      "#cpsReasons",
    );
    renderScore(
      calculatePipScore(sampleValues, PIP_SELL_SCORE_WEIGHTS),
      "#sellScoreValue",
      "#sellScoreConfidence",
      "#sellScoreReasons",
    );
    document.querySelector("#cpsReasons").textContent = "Illustrative sample only; not saved.";
    document.querySelector("#sellScoreReasons").textContent = "Illustrative sample only; not saved.";
  });
  document.querySelector("#clearScores").addEventListener("click", () => {
    for (const input of inputElements.values()) input.value = "";
    updateScores();
  });
  document.querySelector("#analysisSymbol").addEventListener("input", () => {
    resetAnalysisInputs();
    document.querySelector("#researchResult").hidden = true;
    document.querySelector("#researchStatus").textContent = "Load research for this holding before analyzing it.";
    updateResearchEnabled();
  });
  document.querySelector("#loadResearch").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const output = document.querySelector("#researchStatus");
    let requestId = null;
    try {
      requestId = ++researchRequestId;
      const portfolioId = selectedPortfolio();
      const symbol = document.querySelector("#analysisSymbol").value.trim().toUpperCase();
      if (!/^[A-Z0-9][A-Z0-9.-]{0,29}$/.test(symbol)) throw new Error("Enter a valid holding symbol.");
      document.querySelector("#researchResult").hidden = true;
      document.querySelector("#pipMarketPrice").value = "";
      document.querySelector("#pipTargetPrice").value = "";
      document.querySelector("#pipTargetUpside").value = "";
      setBusy(button, true, "Loading research…");
      output.textContent = "Fetching available Yahoo research and the shared market-price snapshot…";
      const research = await apiRequest(
        `/api/pip/portfolios/${encodeURIComponent(portfolioId)}/research`,
        { method: "POST", body: JSON.stringify({ symbol }) },
      );
      if (requestId !== researchRequestId
        || portfolioSelect.value !== portfolioId
        || document.querySelector("#analysisSymbol").value.trim().toUpperCase() !== symbol) return;
      document.querySelector("#pipMarketPrice").value = research.price.price ?? "";
      document.querySelector("#pipTargetPrice").value = research.analyst.target_price ?? "";
      document.querySelector("#pipTargetUpside").value = research.analyst.target_upside_percent ?? "";
      const earningsGrowth = research.growth?.earnings_growth_percent;
      if (earningsGrowth !== null && earningsGrowth !== undefined) {
        document.querySelector("#pipEarningsGrowth").value = earningsGrowth;
      }
      const revenueGrowth = research.growth?.revenue_growth_percent;
      if (revenueGrowth !== null && revenueGrowth !== undefined) {
        document.querySelector("#pipRevenueGrowth").value = revenueGrowth;
      }

      const returned = research.returns;
      const dividendTotal = research.dividends.trailing_365_days_per_share;
      const revisionSummary = Object.entries(research.analyst_revisions?.periods || {})
        .map(([period, counts]) => (
          `${period}: ${counts.up_last_30_days ?? "unavailable"} up, ${counts.down_last_30_days ?? "unavailable"} down (30 days)`
        ))
        .join("; ") || "unavailable";
      const details = [
        `Price: ${research.price.price === null ? "unavailable" : research.price.price} (${research.price.source || "source unavailable"}${research.price.as_of ? `, as of ${research.price.as_of}` : ""}${research.price.stale ? ", marked stale" : ""}).`,
        `Yahoo history (${returned.start_date || "?"} to ${returned.end_date || "?"}, ${returned.basis || "basis unavailable"}): return ${returned.price_return_percent === null ? "unavailable" : `${returned.price_return_percent}%`}; SPY ${returned.spy_return_percent === null ? "unavailable" : `${returned.spy_return_percent}%`}; relative performance ${returned.relative_performance_percentage_points === null ? "unavailable" : `${returned.relative_performance_percentage_points} percentage points`}.`,
        `Analyst consensus: ${research.analyst.rating || "unavailable"}; target upside ${research.analyst.target_upside_percent === null ? "unavailable" : `${research.analyst.target_upside_percent}%`}.`,
        `Yahoo growth: earnings ${research.growth?.earnings_growth_percent ?? "unavailable"}%; revenue ${research.growth?.revenue_growth_percent ?? "unavailable"}%.`,
        `Yahoo EPS revision counts (raw, not converted to a score): ${revisionSummary}.`,
        `Yahoo trailing dividends: ${dividendTotal === null ? "unavailable" : `${dividendTotal} per share`} (not portfolio cash income).`,
      ];
      const result = document.querySelector("#researchResult");
      result.textContent = `${details.join(" ")} ${research.warnings.join(" ")}`;
      result.hidden = false;
      output.textContent = "Available research loaded. Market price, analyst target, and growth inputs were filled where available. Revision counts remain raw; no score conversion was applied.";
    } catch (error) {
      if (requestId === researchRequestId) {
        output.textContent = error.message || "Could not load market research.";
      }
    } finally {
      if (requestId === researchRequestId) {
        setBusy(button, false);
        updateResearchEnabled();
      }
    }
  });
  updateScores();

  document.querySelector("#csvFile").addEventListener("change", async (event) => {
    const file = event.target.files?.[0];
    const output = document.querySelector("#csvStatus");
    const preview = document.querySelector("#csvPreview");
    const tableBody = document.querySelector("#csvRows");
    csvText = null;
    preview.hidden = true;
    tableBody.replaceChildren();
    if (!file) {
      output.textContent = "No file selected.";
      updateImportEnabled();
      return;
    }
    if (file.size > 1_000_000) {
      output.textContent = "Choose a CSV file no larger than 1 MB.";
      updateImportEnabled();
      return;
    }
    try {
      const content = await file.text();
      const records = portfolioImportPreviewFromCsv(content, document.querySelector("#missingCurrency").value);
      csvText = content;
      for (const holding of records.positions) {
        const row = document.createElement("tr");
        for (const value of [
          holding.symbol,
          Number(holding.quantity).toLocaleString(),
          holding.buy_price === null ? "Not provided" : `${holding.currency} ${holding.buy_price}`,
          holding.bought_on || "Not provided",
          holding.currency,
        ]) {
          const cell = document.createElement("td");
          cell.textContent = value;
          row.append(cell);
        }
        tableBody.append(row);
      }
      preview.hidden = !records.positions.length;
      const counts = [
        `${records.positions.length} position${records.positions.length === 1 ? "" : "s"}`,
        `${records.transactions} transaction${records.transactions === 1 ? "" : "s"}`,
        `${records.dividends} dividend${records.dividends === 1 ? "" : "s"}`,
      ];
      output.textContent = `${counts.join(", ")} validated locally from ${file.name}. Select Import to save them to your PIP portfolio.`;
    } catch (error) {
      output.textContent = error.message || "The CSV could not be validated.";
    }
    updateImportEnabled();
  });

  document.querySelector("#importCsv").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const output = document.querySelector("#csvStatus");
    try {
      const portfolioId = selectedPortfolio();
      if (!csvText) throw new Error("Choose and validate a CSV file first.");
      setBusy(button, true, "Importing…");
      output.textContent = "Uploading to the authenticated PIP API…";
      const currency = document.querySelector("#missingCurrency").value.trim();
      const query = currency ? `?default_currency=${encodeURIComponent(currency)}` : "";
      const imported = await apiRequest(
        `/api/pip/portfolios/${encodeURIComponent(portfolioId)}/sync/csv${query}`,
        { method: "POST", body: csvText, contentType: "text/csv" },
      );
      output.textContent = `Saved ${imported.counts.positions} positions, ${imported.counts.transactions} transactions, ${imported.counts.dividends} dividends, and ${imported.counts.accounts} masked accounts to Supabase.`;
    } catch (error) {
      output.textContent = error.message || "CSV import failed.";
    } finally {
      setBusy(button, false);
      updateImportEnabled();
    }
  });

  portfolioSelect.addEventListener("change", async () => {
    resetAnalysisInputs();
    updateImportEnabled();
    updateResearchEnabled();
    updateFlexControls();
    if (!apiConnected) return;
    try {
      await Promise.all([loadRecommendations(), loadFlexConnections()]);
    } catch (error) {
      apiStatus.textContent = error.message || "Could not load recommendations.";
    }
  });

  document.querySelector("#analyzePosition").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const output = document.querySelector("#analysisStatus");
    try {
      const portfolioId = selectedPortfolio();
      const symbol = document.querySelector("#analysisSymbol").value.trim().toUpperCase();
      if (!/^[A-Z0-9][A-Z0-9.-]{0,29}$/.test(symbol)) throw new Error("Enter a valid holding symbol.");
      document.querySelector("#analysisResult").hidden = true;
      const scores = Object.fromEntries([...inputElements].map(([name, input]) => [
        name,
        input.value === "" ? null : Number(input.value),
      ]));
      const entryDate = document.querySelector("#pipEntryDate").value || null;
      const costBasis = optionalNumber("#pipCostBasis", "Cost basis", { min: 0 });
      const marketValue = optionalNumber("#pipMarketValue", "Market value");
      const marketPrice = optionalNumber("#pipMarketPrice", "Market price", { min: 0.01 });
      const dividendsReceived = optionalNumber("#pipDividendsReceived", "Dividends received", { min: 0 });
      const payoutRatio = optionalNumber("#pipPayoutRatio", "Payout ratio", { min: 0, max: 1 });
      const dividendGrowth = optionalNumber("#pipDividendGrowth", "Dividend growth rate");
      const dividendConsistency = optionalNumber("#pipDividendConsistency", "Dividend consistency", { min: 0, max: 1 });
      const earningsGrowth = optionalNumber("#pipEarningsGrowth", "Earnings growth");
      const revenueGrowth = optionalNumber("#pipRevenueGrowth", "Revenue growth");
      const targetPrice = optionalNumber("#pipTargetPrice", "Analyst target price", { min: 0.01 });
      const targetUpside = optionalNumber("#pipTargetUpside", "Target upside");
      const forwardRevisions = optionalNumber("#pipForwardRevisions", "Forward revisions score", { min: 0, max: 100 });
      const peerScores = readPeerScores();
      setBusy(button, true, "Analyzing…");
      output.textContent = "Running portfolio analysis and saving the recommendation…";
      const result = await apiRequest("/api/pip/analysis", {
        method: "POST",
        body: JSON.stringify({
          portfolio_id: portfolioId,
          symbol,
          scores,
          position: {
            entry_date: entryDate,
            cost_basis: costBasis,
            market_value: marketValue,
            market_price: marketPrice,
            dividends_received: dividendsReceived,
          },
          dividends: {
            payout_ratio: payoutRatio,
            dividend_growth_rate: dividendGrowth,
            consistency_score: dividendConsistency,
          },
          growth: {
            earnings_growth_percent: earningsGrowth,
            revenue_growth_percent: revenueGrowth,
          },
          forward: {
            target_price: targetPrice,
            target_upside_percent: targetUpside,
            analyst_revisions_score: forwardRevisions,
          },
          peer_scores: peerScores,
        }),
      });
      showAnalysis(result);
      output.textContent = "Analysis saved. The recommendation is available in the human approval workflow.";
      await loadRecommendations(result.recommendation.id);
    } catch (error) {
      output.textContent = error.message || "Portfolio analysis failed.";
    } finally {
      setBusy(button, false);
    }
  });

  document.querySelector("#refreshRecommendations").addEventListener("click", async () => {
    try {
      await loadRecommendations();
      document.querySelector("#approvalMessage").textContent = "Recommendations refreshed from Supabase.";
    } catch (error) {
      document.querySelector("#approvalMessage").textContent = error.message || "Could not load recommendations.";
    }
  });

  recommendationSelect.addEventListener("change", async () => {
    selectedRecommendation = recommendationSelect.value || null;
    const selected = recommendationSelect.selectedOptions[0];
    document.querySelector("#approvalStatus").textContent = selected?.dataset.status || "Not selected";
    updateTransitionButtons();
    if (!selectedRecommendation) {
      renderEvents([]);
      return;
    }
    try {
      await loadApprovalEvents(selectedRecommendation);
    } catch (error) {
      document.querySelector("#approvalMessage").textContent = error.message || "Could not load audit history.";
    }
  });

  transitions.forEach((button) => {
    button.addEventListener("click", async () => {
      const recommendationId = recommendationSelect.value;
      if (!recommendationId) return;
      try {
        const result = await apiRequest(
          `/api/pip/recommendations/${encodeURIComponent(recommendationId)}/transitions`,
          {
            method: "POST",
            body: JSON.stringify({
              status: button.dataset.transition,
              actor: document.querySelector("#reviewer").value.trim(),
              reason: document.querySelector("#approvalReason").value.trim(),
            }),
          },
        );
        document.querySelector("#approvalStatus").textContent = result.status;
        document.querySelector("#approvalMessage").textContent = `Saved ${result.status} transition and audit event. No order was sent.`;
        await loadRecommendations(recommendationId);
      } catch (error) {
        document.querySelector("#approvalMessage").textContent = error.message || "Approval transition failed.";
      }
    });
  });

  window.addEventListener("stockscanner-pip-auth-ready", () => {
    apiStatus.textContent = apiUrlInput.value
      ? "Authenticated. Select Connect and load portfolios."
      : "Authenticated. Configure the PIP API URL to begin.";
  }, { once: true });
  if (window.stockscannerPipAuth) {
    apiStatus.textContent = apiUrlInput.value
      ? "Authenticated. Select Connect and load portfolios."
      : "Authenticated. Configure the PIP API URL to begin.";
  }
  updateResearchEnabled();
}
