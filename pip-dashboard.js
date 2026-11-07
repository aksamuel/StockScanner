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

export const PIP_DEFAULT_REQUIRED_RETURN_PERCENT = 7;
export const PIP_DEFAULT_REVIEW_TOP_N = 5;
export const PIP_DEFAULT_REVIEW_REPLACEMENT_LIMIT = 5;

const HURDLE_VERDICTS = Object.freeze({
  below: "below the hurdle path",
  meets: "on or ahead of the hurdle path",
  unavailable: "cannot be judged yet",
});

function finiteNumber(value) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function trimmedPercent(value) {
  return `${Number(value.toFixed(2))}%`;
}

export function describePipHurdle(hurdle) {
  if (!hurdle || typeof hurdle !== "object") {
    return ["Return hurdle: unavailable from this API version."];
  }
  const required = finiteNumber(hurdle.required_annual_return_percent);
  const rate = required === null ? "required annual return" : `${trimmedPercent(required)} per year`;
  const lines = [`Return hurdle (${rate}): ${HURDLE_VERDICTS[hurdle.status] || HURDLE_VERDICTS.unavailable}.`];

  const returnPercent = finiteNumber(hurdle.return_percent);
  const pathPercent = finiteNumber(hurdle.hurdle_return_percent);
  if (returnPercent !== null && pathPercent !== null) {
    const days = finiteNumber(hurdle.days_held);
    const lots = finiteNumber(hurdle.lot_count);
    const basis = hurdle.return_basis === "total"
      ? "Total return (price plus dividends received)"
      : "Price-only return";
    const period = days === null
      ? ""
      : ` after ${days} days${lots !== null && lots > 1 ? ` (cost-weighted across ${lots} lots)` : ""}`;
    lines.push(`${basis} is ${returnPercent.toFixed(1)}% against ${pathPercent.toFixed(1)}% needed to match the hurdle path${period}.`);
  }
  const annualized = finiteNumber(hurdle.annualized_return_percent);
  if (annualized !== null) lines.push(`Annualized return: ${annualized.toFixed(1)}% per year.`);
  const shortfall = finiteNumber(hurdle.shortfall_amount);
  if (shortfall !== null && shortfall > 0) lines.push(`Shortfall against the hurdle path: ${shortfall.toFixed(2)}.`);

  const needed = (Array.isArray(hurdle.required_return_by_horizon) ? hurdle.required_return_by_horizon : [])
    .map((item) => [finiteNumber(item?.years), finiteNumber(item?.required_annual_return_percent)])
    .filter(([years, percent]) => years !== null && percent !== null)
    .map(([years, percent]) => `${percent.toFixed(1)}% per year for ${years} year${years === 1 ? "" : "s"}`);
  if (needed.length) lines.push(`Return needed to reach the hurdle path: ${needed.join(", ")}.`);

  const forward = finiteNumber(hurdle.forward_return_percent);
  if (forward !== null && (hurdle.outlook_status === "below" || hurdle.outlook_status === "meets")) {
    lines.push(`Analyst target upside of ${forward.toFixed(1)}% ${hurdle.outlook_status === "below" ? "is below" : "meets or exceeds"} the hurdle.`);
  }

  const scenarios = [];
  const holdingAssumed = finiteNumber(hurdle.holding_assumed_return_percent);
  const yearsToCatchUp = finiteNumber(hurdle.years_to_catch_up);
  if (holdingAssumed !== null && yearsToCatchUp !== null) {
    scenarios.push(yearsToCatchUp === 0
      ? `Scenario: at an assumed ${trimmedPercent(holdingAssumed)} per year this holding is already on or ahead of the hurdle path.`
      : `Scenario: at an assumed ${trimmedPercent(holdingAssumed)} per year this holding would catch up with the hurdle path in about ${yearsToCatchUp.toFixed(1)} years.`);
  }
  const replacementAssumed = finiteNumber(hurdle.replacement_assumed_return_percent);
  const replacementMonths = finiteNumber(hurdle.replacement_months_to_hurdle_gain);
  if (replacementAssumed !== null && replacementMonths !== null && required !== null) {
    scenarios.push(`Scenario: a replacement assumed to earn ${trimmedPercent(replacementAssumed)} per year would take about ${replacementMonths.toFixed(1)} months to gain ${trimmedPercent(required)}.`);
  }
  lines.push(...scenarios);
  if (scenarios.length) {
    lines.push(typeof hurdle.note === "string" && hurdle.note
      ? hurdle.note
      : "Scenario figures are arithmetic from the assumed returns, not forecasts.");
  }

  const reasons = (Array.isArray(hurdle.reasons) ? hurdle.reasons : [])
    .filter((reason) => typeof reason === "string" && reason);
  if (reasons.length) lines.push(`Notes: ${reasons.join(" ")}`);
  return lines;
}

function nonEmptyStrings(values) {
  return (Array.isArray(values) ? values : []).filter((value) => typeof value === "string" && value.trim());
}

function pluralize(count, singular) {
  return `${count} ${count === 1 ? singular : `${singular}s`}`;
}

export function describePipReviewSummary(review) {
  const summary = review && typeof review === "object" ? review.summary : null;
  if (!summary || typeof summary !== "object") {
    return ["Portfolio review: unavailable from this API version."];
  }
  const required = finiteNumber(review.required_annual_return_percent);
  const rate = required === null ? "the required annual return" : `${trimmedPercent(required)} per year`;
  const holdings = finiteNumber(summary.holdings);
  const lines = [holdings === null
    ? `Reviewed open holdings against ${rate}.`
    : `Reviewed ${pluralize(holdings, "open holding")} against ${rate}.`];

  const minimumDays = finiteNumber(review.minimum_holding_days);
  const breakdown = [
    [summary.behind_hurdle, "behind the hurdle path"],
    [summary.meeting_hurdle, "on or ahead of it"],
    [summary.held_under_minimum, minimumDays === null ? "held under the minimum holding period" : `held under ${minimumDays} days`],
    [summary.not_analysable, "could not be compared"],
  ]
    .map(([count, label]) => [finiteNumber(count), label])
    .filter(([count]) => count !== null)
    .map(([count, label]) => `${count} ${label}`);
  if (breakdown.length) lines.push(`${breakdown.join("; ")}.`);

  const shown = Array.isArray(review.top) ? review.top.length : 0;
  const behind = finiteNumber(summary.behind_hurdle);
  if (shown === 0) {
    lines.push("No holding is ranked as behind the hurdle path.");
  } else if (behind !== null && behind > shown) {
    lines.push(`Advice is shown for the ${shown === 1 ? "holding" : `${shown} holdings`} furthest behind the hurdle path.`);
  } else {
    lines.push(`Advice is shown for ${shown === 1 ? "the holding" : `all ${shown} holdings`} behind the hurdle path.`);
  }
  return lines;
}

export function describePipReviewTitle(entry) {
  const symbol = typeof entry?.symbol === "string" && entry.symbol.trim() ? entry.symbol.trim() : "Unknown holding";
  const currency = typeof entry?.currency === "string" && entry.currency.trim() ? ` (${entry.currency.trim()})` : "";
  const rank = finiteNumber(entry?.rank);
  return `${rank === null ? "" : `${rank}. `}${symbol}${currency}`;
}

function describePipReviewDeadMoney(deadMoney) {
  if (!deadMoney || typeof deadMoney !== "object") return ["Dead money: unavailable from this API version."];
  const verdict = deadMoney.is_dead_money === true
    ? "flagged for review"
    : deadMoney.is_dead_money === false
      ? "not flagged"
      : "verdict withheld";
  const confidence = finiteNumber(deadMoney.confidence);
  const lines = [confidence === null
    ? `Dead money: ${verdict}.`
    : `Dead money: ${verdict} (${(Math.min(1, Math.max(0, confidence)) * 100).toFixed(0)}% input confidence).`];
  const reasons = nonEmptyStrings(deadMoney.reasons);
  if (reasons.length) lines.push(`Dead-money evidence: ${reasons.join(" ")}`);
  return lines;
}

function describePipReviewReplacements(replacements) {
  if (!replacements || typeof replacements !== "object") return ["Replacements: unavailable from this API version."];
  const reasons = nonEmptyStrings(replacements.reasons).join(" ");
  const withReasons = (text) => (reasons ? `${text} ${reasons}` : text);
  if (replacements.compared !== true) return [withReasons("Replacements: not compared.")];
  const candidates = (Array.isArray(replacements.candidates) ? replacements.candidates : [])
    .map((candidate) => [candidate?.symbol, finiteNumber(candidate?.score), finiteNumber(candidate?.expected_benefit)])
    .filter(([symbol, score]) => typeof symbol === "string" && symbol.trim() && score !== null);
  if (!candidates.length) return [withReasons("Replacements: none suggested.")];
  return candidates.map(([symbol, score, benefit]) => (
    `Replacement candidate ${symbol.trim()}: score ${score.toFixed(1)}${benefit === null ? "" : `, ${benefit.toFixed(1)} points above this holding's CPS`}.`
  ));
}

export function describePipReviewHolding(entry) {
  if (!entry || typeof entry !== "object") return [];
  const hurdle = entry.hurdle && typeof entry.hurdle === "object" ? entry.hurdle : null;
  const lines = [];
  const excess = finiteNumber(hurdle?.excess_return_percentage_points);
  if (excess !== null) {
    const basis = hurdle.return_basis === "price_only" ? " (price-only)" : "";
    const gap = `${Math.abs(excess).toFixed(1)} percentage points`;
    lines.push(excess < 0
      ? `Behind the hurdle path by ${gap}${basis}.`
      : `Ahead of the hurdle path by ${gap}${basis}.`);
  }
  lines.push(...describePipHurdle(hurdle));
  const cps = finiteNumber(entry.cps);
  lines.push(cps === null
    ? "No saved CPS for this holding; analyze it to save one."
    : `Saved CPS: ${cps.toFixed(1)} / 100.`);
  lines.push(...describePipReviewDeadMoney(entry.dead_money));
  lines.push(...describePipReviewReplacements(entry.replacements));
  return lines;
}

export function describePipReviewSkipped(skipped) {
  return (Array.isArray(skipped) ? skipped : []).flatMap((group) => {
    if (!group || typeof group !== "object") return [];
    const symbols = nonEmptyStrings(group.symbols).map((symbol) => symbol.trim());
    const count = Math.max(finiteNumber(group.count) ?? 0, symbols.length);
    if (count === 0) return [];
    const message = typeof group.message === "string" && group.message.trim()
      ? group.message.trim()
      : "These holdings could not be compared.";
    const more = count > symbols.length ? ` and ${count - symbols.length} more` : "";
    const affected = symbols.length ? ` Affected: ${symbols.join(", ")}${more}.` : "";
    return [`${pluralize(count, "holding")} not compared. ${message}${affected}`];
  });
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
  const flexPositionsOnly = document.querySelector("#flexPositionsOnly");
  const reviewStatus = document.querySelector("#reviewStatus");
  let csvText = null;
  let portfolios = [];
  let apiConnected = false;
  let selectedRecommendation = null;
  let researchRequestId = 0;
  let reviewRequestId = 0;

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

  function optionalWholeNumber(id, label, bounds) {
    const value = optionalNumber(id, label, bounds);
    if (value !== null && !Number.isInteger(value)) throw new Error(`${label} must be a whole number.`);
    return value;
  }

  function readPeerScores(id = "#pipPeerScores", { unique = false, max = null } = {}) {
    const raw = document.querySelector(id).value.trim();
    if (!raw) return [];
    const scores = raw.split(",").map((entry) => {
      const [symbolValue, scoreValue, ...extra] = entry.split(":");
      const symbol = symbolValue.trim().toUpperCase();
      const score = Number(scoreValue);
      if (extra.length || !/^[A-Z0-9][A-Z0-9.-]{0,29}$/.test(symbol)
        || !scoreValue?.trim() || !Number.isFinite(score) || score < 0 || score > 100) {
        throw new Error(`Invalid replacement candidate: ${entry.trim()}. Use SYMBOL:score from 0 to 100.`);
      }
      return { symbol, score };
    });
    if (max !== null && scores.length > max) throw new Error(`Enter at most ${max} replacement candidates.`);
    if (unique && new Set(scores.map((candidate) => candidate.symbol)).size !== scores.length) {
      throw new Error("Each replacement candidate symbol may appear only once.");
    }
    return scores;
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
      "#pipHoldingAssumedReturn",
      "#pipReplacementAssumedReturn",
      "#pipPeerScores",
    ]) {
      document.querySelector(id).value = "";
    }
    document.querySelector("#pipRequiredReturn").value = String(PIP_DEFAULT_REQUIRED_RETURN_PERCENT);
    document.querySelector("#researchResult").hidden = true;
    document.querySelector("#analysisResult").hidden = true;
    updateScores();
  }

  function clearReviewResult() {
    document.querySelector("#reviewResult").hidden = true;
    document.querySelector("#reviewResult").replaceChildren();
  }

  function resetReview() {
    reviewRequestId += 1;
    setBusy(document.querySelector("#runReview"), false);
    document.querySelector("#reviewRequiredReturn").value = String(PIP_DEFAULT_REQUIRED_RETURN_PERCENT);
    document.querySelector("#reviewTopN").value = String(PIP_DEFAULT_REVIEW_TOP_N);
    document.querySelector("#reviewReplacementLimit").value = String(PIP_DEFAULT_REVIEW_REPLACEMENT_LIMIT);
    document.querySelector("#reviewCandidates").value = "";
    reviewStatus.textContent = "";
    clearReviewResult();
  }

  function resetForPortfolioChange() {
    resetAnalysisInputs();
    resetReview();
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
        const portfolioId = portfolioSelect.value;
        const positionsOnly = Boolean(flexPositionsOnly?.checked);
        if (!window.confirm(
          "Does this unfiltered Flex Query include all stock positions for every included account? "
          + "Sync replaces earlier Flex positions for those accounts. CSV/manual imports and history are retained."
          + (positionsOnly ? " This sync skips trade and dividend history." : ""),
        )) return;
        setBusy(syncButton, true, "Syncing…");
        flexStatus.textContent = `Requesting a read-only Flex statement for ${name.textContent}…`;
        try {
          const health = await apiRequest("/healthz");
          if (health?.flex_position_snapshot_sync !== 1) {
            throw new Error("The PIP API must be updated before safe Flex position sync is available.");
          }
          if (positionsOnly && health?.flex_positions_only_sync !== 1) {
            throw new Error("The PIP API must be updated before positions-only Flex sync is available.");
          }
          if (portfolioSelect.value !== portfolioId) {
            throw new Error("The selected portfolio changed. Start the Flex sync again.");
          }
          const result = await apiRequest(
            `/api/pip/portfolios/${encodeURIComponent(portfolioId)}/ibkr-flex-connections/${encodeURIComponent(connection.id)}/sync`,
            {
              method: "POST",
              body: JSON.stringify(positionsOnly
                ? { confirm_unfiltered: true, positions_only: true }
                : { confirm_unfiltered: true }),
            },
          );
          if (portfolioSelect.value !== portfolioId) {
            flexStatus.textContent = "Flex sync completed for the previously selected portfolio.";
            return;
          }
          await loadFlexConnections();
          if (portfolioSelect.value !== portfolioId) return;
          const counts = result.counts || {};
          const accountSummary = (result.accounts || [])
            .map((account) => `${account.masked_account_id || "masked account"} (${account.currency || "currency unavailable"}; statement ${account.statement_date || "date unavailable"})`)
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
    if (portfolioSelect.value !== previous) resetForPortfolioChange();
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
    const hurdleText = document.createElement("p");
    hurdleText.textContent = describePipHurdle(modules.hurdle).join(" ");
    container.append(heading, detail, reasons, hurdleText, assessmentText);
    container.hidden = false;
  }

  function reviewElement(tag, text, className = "") {
    const element = document.createElement(tag);
    element.textContent = text;
    if (className) element.className = className;
    return element;
  }

  function showReview(review) {
    const children = [reviewElement("h3", "Portfolio review")];
    for (const line of describePipReviewSummary(review)) children.push(reviewElement("p", line));
    if (review.summary?.truncated === true) {
      children.push(reviewElement(
        "p",
        "Some holdings were not reviewed because the position list was longer than the review limit. This ranking may be incomplete.",
        "notice",
      ));
    }
    for (const entry of Array.isArray(review.top) ? review.top : []) {
      const card = document.createElement("div");
      card.className = "review-holding";
      card.append(reviewElement("h3", describePipReviewTitle(entry)));
      for (const line of describePipReviewHolding(entry)) card.append(reviewElement("p", line));
      children.push(card);
    }
    const skipped = describePipReviewSkipped(review.skipped);
    if (skipped.length) {
      children.push(reviewElement("h3", "Not compared"));
      for (const line of skipped) children.push(reviewElement("p", line));
    }
    const notes = nonEmptyStrings(review.notes);
    if (notes.length) {
      children.push(reviewElement("h3", "Notes"));
      const list = document.createElement("ul");
      for (const note of notes) list.append(reviewElement("li", note));
      children.push(list);
    }
    const container = document.querySelector("#reviewResult");
    container.replaceChildren(...children);
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
      if (portfolioSelect.value !== created.id) resetForPortfolioChange();
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
    resetForPortfolioChange();
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
      const requiredReturn = optionalNumber("#pipRequiredReturn", "Required annual return", { min: 0, max: 100 });
      const holdingAssumedReturn = optionalNumber("#pipHoldingAssumedReturn", "What-if return for this holding", { min: -99.99, max: 1000 });
      const replacementAssumedReturn = optionalNumber("#pipReplacementAssumedReturn", "What-if return for a replacement", { min: -99.99, max: 1000 });
      const peerScores = readPeerScores();
      setBusy(button, true, "Analyzing…");
      output.textContent = "Running portfolio analysis and saving the recommendation…";
      const health = await apiRequest("/healthz");
      if (health?.hurdle_analysis !== 1) {
        throw new Error("The PIP API must be updated before return hurdle analysis is available.");
      }
      if (portfolioSelect.value !== portfolioId) {
        throw new Error("The selected portfolio changed. Start the analysis again.");
      }
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
          hurdle: {
            ...(requiredReturn === null ? {} : { required_annual_return_percent: requiredReturn }),
            holding_assumed_return_percent: holdingAssumedReturn,
            replacement_assumed_return_percent: replacementAssumedReturn,
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

  document.querySelector("#runReview").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    let requestId = null;
    try {
      clearReviewResult();
      const portfolioId = selectedPortfolio();
      const requiredReturn = optionalNumber("#reviewRequiredReturn", "Required annual return", { min: 0, max: 100 });
      const topN = optionalWholeNumber("#reviewTopN", "Number of holdings", { min: 1, max: 20 });
      const replacementLimit = optionalWholeNumber("#reviewReplacementLimit", "Replacements per holding", { min: 1, max: 10 });
      const candidates = readPeerScores("#reviewCandidates", { unique: true, max: 500 });
      requestId = ++reviewRequestId;
      setBusy(button, true, "Reviewing…");
      reviewStatus.textContent = "Reviewing saved positions…";
      const health = await apiRequest("/healthz");
      if (requestId !== reviewRequestId) return;
      if (health?.portfolio_review !== 1) {
        throw new Error("The PIP API must be updated before portfolio review is available.");
      }
      if (portfolioSelect.value !== portfolioId) {
        throw new Error("The selected portfolio changed. Run the review again.");
      }
      const payload = await apiRequest(`/api/pip/portfolios/${encodeURIComponent(portfolioId)}/review`, {
        method: "POST",
        body: JSON.stringify({
          ...(requiredReturn === null ? {} : { required_annual_return_percent: requiredReturn }),
          ...(topN === null ? {} : { top_n: topN }),
          ...(replacementLimit === null ? {} : { replacement_limit: replacementLimit }),
          peer_scores: candidates,
        }),
      });
      if (requestId !== reviewRequestId) return;
      if (portfolioSelect.value !== portfolioId) {
        throw new Error("The selected portfolio changed. Run the review again.");
      }
      if (!payload || typeof payload.review !== "object" || payload.review === null) {
        throw new Error("The PIP API returned an unexpected review response.");
      }
      showReview(payload.review);
      reviewStatus.textContent = "Review complete. It is read-only: nothing was saved and no orders were placed.";
    } catch (error) {
      if (requestId === null || requestId === reviewRequestId) {
        reviewStatus.textContent = error.message || "Portfolio review failed.";
      }
    } finally {
      if (requestId !== null && requestId === reviewRequestId) setBusy(button, false);
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
