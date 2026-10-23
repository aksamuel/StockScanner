import { portfolioRowsFromCsv } from "./portfolio-analysis.js";

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

export const PIP_APPROVAL_TRANSITIONS = Object.freeze({
  proposed: ["under_review", "cancelled", "expired"],
  under_review: ["approved", "rejected", "escalated", "cancelled", "expired"],
  approved: ["submitted", "escalated", "cancelled"],
  rejected: [],
  expired: [],
  submitted: [],
  cancelled: [],
  escalated: ["under_review", "approved", "rejected", "cancelled", "expired"],
});

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

export function transitionPipApproval(currentStatus, nextStatus, actor, reason, now = new Date()) {
  if (!PIP_APPROVAL_TRANSITIONS[currentStatus]?.includes(nextStatus)) {
    throw new Error(`Cannot transition recommendation from ${currentStatus} to ${nextStatus}.`);
  }
  if (nextStatus === "approved" && (!actor?.trim() || !reason?.trim())) {
    throw new Error("Explicit human approval requires an actor and a reason.");
  }
  return {
    status: nextStatus,
    event: {
      from_status: currentStatus,
      to_status: nextStatus,
      actor: actor?.trim() || null,
      reason: reason?.trim() || null,
      created_at: now.toISOString(),
    },
  };
}

export { portfolioRowsFromCsv };

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
  const scoreInputs = document.querySelector("#scoreInputs");
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
    scoreInputs.append(label);
    inputElements.set(name, input);
  }

  document.querySelector("#loadSample").addEventListener("click", () => {
    for (const [name, input] of inputElements) input.value = String(sampleValues[name]);
    updateScores();
  });
  document.querySelector("#clearScores").addEventListener("click", () => {
    for (const input of inputElements.values()) input.value = "";
    updateScores();
  });
  updateScores();

  document.querySelector("#csvFile").addEventListener("change", async (event) => {
    const file = event.target.files?.[0];
    const status = document.querySelector("#csvStatus");
    const preview = document.querySelector("#csvPreview");
    const body = document.querySelector("#csvRows");
    preview.hidden = true;
    body.replaceChildren();
    if (!file) {
      status.textContent = "No file selected.";
      return;
    }
    if (file.size > 1_000_000) {
      status.textContent = "Choose a CSV file no larger than 1 MB.";
      return;
    }
    try {
      const rows = portfolioRowsFromCsv(await file.text(), document.querySelector("#missingCurrency").value);
      for (const holding of rows) {
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
        body.append(row);
      }
      preview.hidden = false;
      status.textContent = `${rows.length} holding${rows.length === 1 ? "" : "s"} validated from ${file.name}. This preview remains in this browser only.`;
    } catch (error) {
      status.textContent = error.message || "The CSV could not be validated.";
    }
  });

  let approvalStatus = "proposed";
  const approvalEvents = [];
  const terminalStatuses = new Set(["approved", "rejected", "expired", "submitted", "cancelled"]);
  document.querySelectorAll("[data-transition]").forEach((button) => {
    button.addEventListener("click", () => {
      const actor = document.querySelector("#reviewer").value;
      const reason = document.querySelector("#approvalReason").value;
      try {
        const result = transitionPipApproval(approvalStatus, button.dataset.transition, actor, reason);
        approvalStatus = result.status;
        approvalEvents.push(result.event);
        document.querySelector("#approvalStatus").textContent = approvalStatus;
        document.querySelector("#approvalMessage").textContent = "Transition recorded in page memory only.";
        const list = document.querySelector("#approvalEvents");
        if (list.querySelector(".empty-state")) list.replaceChildren();
        const item = document.createElement("li");
        item.textContent = `${result.event.from_status} → ${result.event.to_status} · ${result.event.actor || "system"} · ${result.event.reason || "No reason supplied"}`;
        list.append(item);
        document.querySelectorAll("[data-transition]").forEach((control) => {
          control.disabled = terminalStatuses.has(approvalStatus)
            || !PIP_APPROVAL_TRANSITIONS[approvalStatus]?.includes(control.dataset.transition);
        });
      } catch (error) {
        document.querySelector("#approvalMessage").textContent = error.message;
      }
    });
  });
  document.querySelectorAll("[data-transition]").forEach((button) => {
    button.disabled = !PIP_APPROVAL_TRANSITIONS[approvalStatus]?.includes(button.dataset.transition);
  });
}
