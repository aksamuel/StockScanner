export const DEFAULT_PROFIT_REVIEW_PERCENT = 7;
export const DEFAULT_LOSS_REVIEW_PERCENT = -10;

export function parseCsv(source) {
  const rows = [];
  let row = [];
  let field = "";
  let quoted = false;
  const text = String(source || "").replace(/^\uFEFF/, "");
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    if (quoted && character === '"' && text[index + 1] === '"') {
      field += '"';
      index += 1;
    } else if (character === '"') {
      quoted = !quoted;
    } else if (character === "," && !quoted) {
      row.push(field);
      field = "";
    } else if ((character === "\n" || character === "\r") && !quoted) {
      if (character === "\r" && text[index + 1] === "\n") index += 1;
      row.push(field);
      if (row.some((value) => value.trim())) rows.push(row);
      row = [];
      field = "";
    } else {
      field += character;
    }
  }
  if (quoted) throw new Error("The CSV contains an unclosed quoted value.");
  if (field || row.length) {
    row.push(field);
    if (row.some((value) => value.trim())) rows.push(row);
  }
  return rows;
}

function numberValue(value, label, rowNumber, { required = false, nonzero = false } = {}) {
  const text = String(value || "").replace(/[,$%]/g, "").trim();
  if (!text && !required) return null;
  const parsed = Number(text);
  if (!Number.isFinite(parsed) || (nonzero && parsed === 0)) {
    throw new Error(`Row ${rowNumber}: ${label} must be ${nonzero ? "a non-zero" : "a valid"} number.`);
  }
  return parsed;
}

function dateValue(value, rowNumber) {
  const text = String(value || "").trim();
  if (!text) return null;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(text) || Number.isNaN(Date.parse(`${text}T00:00:00Z`))) {
    throw new Error(`Row ${rowNumber}: buy_date must use YYYY-MM-DD.`);
  }
  return text;
}

export function portfolioRowsFromCsv(source) {
  const rows = parseCsv(source);
  if (rows.length < 2) throw new Error("The CSV must contain a header and at least one holding.");
  if (rows.length > 1001) throw new Error("A CSV import is limited to 1000 holdings.");
  const headers = rows[0].map((value) => value.trim().toLowerCase());
  const columnAliases = {
    symbol: ["symbol"],
    quantity: ["quantity"],
    buy_price: ["buy_price", "costbasisprice", "cost_basis_price"],
    buy_date: ["buy_date", "opendatetime", "open_date_time", "trade_date"],
  };
  const columnIndexes = Object.fromEntries(Object.entries(columnAliases).map(([name, aliases]) => [
    name,
    aliases.map((alias) => headers.indexOf(alias)).find((index) => index >= 0) ?? -1,
  ]));
  for (const required of Object.keys(columnAliases)) {
    if (columnIndexes[required] < 0) throw new Error(`Missing required CSV column: ${required}`);
  }
  const get = (row, name) => {
    const index = columnIndexes[name] ?? headers.indexOf(name);
    return index >= 0 ? row[index] || "" : "";
  };
  return rows.slice(1).map((row, index) => {
    const rowNumber = index + 2;
    const symbol = get(row, "symbol").trim().toUpperCase().replace(/\s+/g, "-");
    if (!/^[A-Z0-9][A-Z0-9.-]{0,29}$/.test(symbol)) {
      throw new Error(`Row ${rowNumber}: invalid ticker symbol.`);
    }
    const boughtOn = dateValue(get(row, "buy_date"), rowNumber);
    const currency = (get(row, "currency") || "USD").trim().toUpperCase();
    if (!/^[A-Z]{3}$/.test(currency)) throw new Error(`Row ${rowNumber}: invalid currency code.`);
    const notes = get(row, "notes").trim();
    if (notes.length > 500) throw new Error(`Row ${rowNumber}: notes exceed 500 characters.`);
    return {
      position_key: `${symbol}:${boughtOn || "SUMMARY"}:${index + 1}`,
      symbol,
      description: null,
      asset_class: "STK",
      currency,
      quantity: numberValue(get(row, "quantity"), "quantity", rowNumber, { required: true, nonzero: true }),
      buy_price: numberValue(get(row, "buy_price"), "buy_price", rowNumber, { required: true }),
      bought_on: boughtOn,
      current_price: null,
      current_price_at: null,
      market_value: null,
      unrealized_pnl: null,
      target_price: numberValue(get(row, "target_price"), "target_price", rowNumber),
      stop_loss: numberValue(get(row, "stop_loss"), "stop_loss", rowNumber),
      notes: notes || null,
    };
  });
}

export function detectedPortfolioBroker(source) {
  const [header = []] = parseCsv(source);
  const headers = header.map((value) => value.trim().toLowerCase());
  return ["clientaccountid", "symbol", "quantity", "costbasisprice", "opendatetime"]
    .every((column) => headers.includes(column)) ? "IBKR" : null;
}

export function holdingReturnPercent(holding, currentPrice) {
  const buyPrice = Number(holding.buy_price);
  const quantity = Number(holding.quantity);
  if (!Number.isFinite(currentPrice) || currentPrice < 0 || !Number.isFinite(buyPrice) || buyPrice <= 0) {
    return null;
  }
  return (quantity < 0 ? buyPrice - currentPrice : currentPrice - buyPrice) / buyPrice * 100;
}

export function recommendedTargetPrice(holding, context = {}) {
  const optionalNumber = (value) => value === null || value === undefined || value === ""
    ? Number.NaN
    : Number(value);
  const manualTarget = optionalNumber(holding.target_price);
  if (Number.isFinite(manualTarget) && manualTarget > 0) {
    return {
      price: manualTarget,
      type: "manual",
      source: "Manual target",
      candidates: [{ price: manualTarget, source: "Manual target" }],
    };
  }

  const buyPrice = optionalNumber(holding.buy_price);
  if (!Number.isFinite(buyPrice) || buyPrice <= 0) return null;
  const isShort = Number(holding.quantity) < 0;
  const reviewTarget = buyPrice * (1 + (isShort ? -1 : 1) * DEFAULT_PROFIT_REVIEW_PERCENT / 100);
  const candidates = [
    { price: reviewTarget, source: `${DEFAULT_PROFIT_REVIEW_PERCENT}% return objective` },
    { price: optionalNumber(context.technicalTarget), source: "Technical Target 1" },
    { price: optionalNumber(context.resistanceTarget), source: "Technical resistance" },
    { price: optionalNumber(context.analystTarget), source: "Analyst target proxy" },
  ].filter(({ price }) => (
    Number.isFinite(price) && price > 0 && (isShort ? price <= buyPrice : price >= buyPrice)
  ));
  if (!candidates.length) return null;

  const selectedPrice = isShort
    ? Math.max(...candidates.map(({ price }) => price))
    : Math.min(...candidates.map(({ price }) => price));
  const tolerance = Math.max(0.000001, selectedPrice * 0.000001);
  const selectedSources = candidates
    .filter(({ price }) => Math.abs(price - selectedPrice) <= tolerance)
    .map(({ source }) => source);
  return {
    price: selectedPrice,
    type: "automatic",
    source: selectedSources.join(" + "),
    candidates,
  };
}

export function daysHeld(boughtOn, now = new Date()) {
  if (!boughtOn) return null;
  const bought = new Date(`${boughtOn}T00:00:00Z`);
  if (Number.isNaN(bought.getTime())) return null;
  return Math.max(0, Math.floor((now.getTime() - bought.getTime()) / 86_400_000));
}

export function equalWeightTopTwentyMetrics(chartData) {
  const labels = Array.isArray(chartData?.labels) ? chartData.labels : [];
  const values = Array.isArray(chartData?.top20) ? chartData.top20 : [];
  if (labels.length < 2 || labels.length !== values.length) return null;
  const firstDate = new Date(`${labels[0]}T00:00:00Z`);
  const lastDate = new Date(`${labels.at(-1)}T00:00:00Z`);
  const firstValue = Number(values[0]);
  const lastValue = Number(values.at(-1));
  const elapsedDays = Math.round((lastDate.getTime() - firstDate.getTime()) / 86_400_000);
  if (
    Number.isNaN(firstDate.getTime()) || Number.isNaN(lastDate.getTime())
    || elapsedDays <= 0 || !Number.isFinite(firstValue) || firstValue <= 0
    || !Number.isFinite(lastValue) || lastValue <= 0
  ) return null;
  const growthFactor = lastValue / firstValue;
  const dailyReturn = growthFactor ** (1 / elapsedDays) - 1;
  const annualizedReturn = (1 + dailyReturn) ** 365.25 - 1;
  return {
    startDate: labels[0],
    endDate: labels.at(-1),
    elapsedDays,
    totalReturnPercent: (growthFactor - 1) * 100,
    annualizedReturnPercent: annualizedReturn * 100,
    dailyReturn,
  };
}

export function estimatedBreakevenDays(buyPrice, currentPrice, benchmarkMetrics) {
  const purchased = Number(buyPrice);
  const current = Number(currentPrice);
  const dailyReturn = Number(benchmarkMetrics?.dailyReturn);
  if (!Number.isFinite(purchased) || purchased <= 0 || !Number.isFinite(current) || current <= 0) {
    return null;
  }
  if (current >= purchased) return 0;
  if (!Number.isFinite(dailyReturn) || dailyReturn <= 0) return null;
  const days = Math.log(purchased / current) / Math.log(1 + dailyReturn);
  return Number.isFinite(days) && days >= 0 ? Math.ceil(days) : null;
}

export function profitTimingLabel(returnPercent, heldDays) {
  if (returnPercent === null) return "Price unavailable";
  const duration = heldDays === null ? "buy date needed" : `${heldDays} day${heldDays === 1 ? "" : "s"} held`;
  if (returnPercent > 0) return `Profitable · ${duration}`;
  if (returnPercent < 0) return `Not profitable · ${duration}`;
  return `Break-even · ${duration}`;
}

export function sellReviewSignal(holding, currentPrice, returnPercent) {
  if (!Number.isFinite(currentPrice) || returnPercent === null) {
    return { code: "unavailable", label: "Price unavailable" };
  }
  const isShort = Number(holding.quantity) < 0;
  const target = Number(holding.target_price);
  const stop = Number(holding.stop_loss);
  if (Number.isFinite(target) && target > 0 && (isShort ? currentPrice <= target : currentPrice >= target)) {
    return { code: "sell-review", label: "Sell review · target reached" };
  }
  if (Number.isFinite(stop) && stop > 0 && (isShort ? currentPrice >= stop : currentPrice <= stop)) {
    return { code: "risk-review", label: "Risk review · stop reached" };
  }
  if (returnPercent >= DEFAULT_PROFIT_REVIEW_PERCENT) {
    return { code: "sell-review", label: `Profit review · +${DEFAULT_PROFIT_REVIEW_PERCENT}% rule` };
  }
  if (returnPercent <= DEFAULT_LOSS_REVIEW_PERCENT) {
    return { code: "risk-review", label: `Risk review · ${DEFAULT_LOSS_REVIEW_PERCENT}% rule` };
  }
  return { code: "monitor", label: "Hold / monitor" };
}

export function portfolioConcentrationPercent(holdings) {
  const bySymbol = {};
  let grossMarketValue = 0;
  for (const holding of holdings || []) {
    const price = Number(holding?.quote?.price);
    const quantity = Number(holding?.quantity);
    if (!Number.isFinite(price) || price < 0 || !Number.isFinite(quantity)) continue;
    const marketValue = Math.abs(price * quantity);
    bySymbol[holding.symbol] = (bySymbol[holding.symbol] || 0) + marketValue;
    grossMarketValue += marketValue;
  }
  if (grossMarketValue <= 0) return {};
  return Object.fromEntries(Object.entries(bySymbol).map(([symbol, value]) => [
    symbol,
    value / grossMarketValue * 100,
  ]));
}

export function portfolioActionDecision(holding, context = {}) {
  const optionalNumber = (value) => value === null || value === undefined || value === "" ? Number.NaN : Number(value);
  const currentPrice = optionalNumber(context.currentPrice);
  const returnPercent = optionalNumber(context.returnPercent);
  const heldDays = optionalNumber(context.heldDays);
  const concentrationPercent = optionalNumber(context.concentrationPercent);
  const scannerRecommendation = String(context.scannerRecommendation || "unavailable")
    .trim().toLowerCase().replace(/\s+/g, "-");
  const scannerScore = optionalNumber(context.scannerScore);
  const isShort = Number(holding.quantity) < 0;
  const targetDetails = context.recommendedTarget || recommendedTargetPrice(holding, context);
  const target = Number(targetDetails?.price);
  const stop = Number(holding.stop_loss);
  const hasPrice = Number.isFinite(currentPrice) && currentPrice >= 0;
  const hasReturn = Number.isFinite(returnPercent);
  const targetHit = hasPrice && Number.isFinite(target) && target > 0
    && (isShort ? currentPrice <= target : currentPrice >= target);
  const stopHit = hasPrice && Number.isFinite(stop) && stop > 0
    && (isShort ? currentPrice >= stop : currentPrice <= stop);
  const scannerLabel = scannerRecommendation === "unavailable"
    ? "Scanner unavailable"
    : scannerRecommendation.split("-").map((word) => word[0].toUpperCase() + word.slice(1)).join(" ");
  const scannerReason = Number.isFinite(scannerScore)
    ? `${scannerLabel} (${scannerScore.toFixed(0)})`
    : scannerLabel;
  const decision = (code, label, reasons, priority) => ({ code, label, reasons, priority });

  if (!hasPrice || !hasReturn) {
    return decision("unavailable", "Data needed", ["Present price or buy price is unavailable."], -1);
  }
  if (stopHit) {
    return decision("sell", "Sell review", [`Stop-loss ${stop.toFixed(2)} has been reached.`, scannerReason], 3);
  }
  if (targetHit) {
    const targetKind = targetDetails?.type === "manual" ? "Manual target" : "Automatic target";
    return decision("sell", "Sell review", [
      `${targetKind} ${target.toFixed(2)} has been reached (${targetDetails?.source || "target rule"}).`,
      scannerReason,
    ], 3);
  }
  if (scannerRecommendation === "avoid" && returnPercent <= DEFAULT_LOSS_REVIEW_PERCENT) {
    return decision("sell", "Sell review", [
      `${returnPercent.toFixed(2)}% return is below the ${DEFAULT_LOSS_REVIEW_PERCENT}% risk threshold.`,
      scannerReason,
    ], 3);
  }
  if (Number.isFinite(concentrationPercent) && concentrationPercent >= 20) {
    return decision("partial-sell", "Partial sell review", [
      `${concentrationPercent.toFixed(1)}% portfolio concentration exceeds the 20% high-concentration threshold.`,
      scannerReason,
    ], 2);
  }
  if (scannerRecommendation === "avoid" && returnPercent > 0) {
    return decision("partial-sell", "Partial sell review", [
      `Protect a ${returnPercent.toFixed(2)}% gain while the scanner rating is Avoid.`,
      scannerReason,
    ], 2);
  }
  if (
    returnPercent >= DEFAULT_PROFIT_REVIEW_PERCENT
    && (
      ["watch", "avoid"].includes(scannerRecommendation)
      || (Number.isFinite(heldDays) && heldDays >= 180)
      || (Number.isFinite(concentrationPercent) && concentrationPercent >= 10)
    )
  ) {
    const secondaryReason = Number.isFinite(concentrationPercent) && concentrationPercent >= 10
      ? `${concentrationPercent.toFixed(1)}% portfolio concentration.`
      : Number.isFinite(heldDays) && heldDays >= 180
        ? `${heldDays} days held.`
        : scannerReason;
    return decision("partial-sell", "Partial sell review", [
      `${returnPercent.toFixed(2)}% return exceeds the ${DEFAULT_PROFIT_REVIEW_PERCENT}% profit-review threshold.`,
      secondaryReason,
    ], 2);
  }
  if (
    returnPercent <= DEFAULT_LOSS_REVIEW_PERCENT
    && (scannerRecommendation === "watch" || (Number.isFinite(heldDays) && heldDays >= 180))
  ) {
    return decision("partial-sell", "Partial sell review", [
      `${returnPercent.toFixed(2)}% return is below the ${DEFAULT_LOSS_REVIEW_PERCENT}% risk threshold.`,
      Number.isFinite(heldDays) ? `${heldDays} days held; reassess capital efficiency.` : scannerReason,
    ], 2);
  }

  const holdReasons = [scannerReason];
  if (Number.isFinite(concentrationPercent)) {
    holdReasons.push(`${concentrationPercent.toFixed(1)}% of known portfolio market value.`);
  }
  return decision("hold", "Hold / monitor", holdReasons, 1);
}
