const REQUIRED_COLUMNS = {
  symbol: ["symbol"],
  quantity: ["quantity"],
  buyPrice: ["buy_price", "costbasisprice", "cost_basis_price"],
  buyDate: ["buy_date", "opendatetime", "open_date_time", "trade_date"],
};

export function parseSellAdvisorCsv(source, missingCurrency = "") {
  const text = String(source || "").replace(/^\uFEFF/, "");
  const rows = [];
  let row = [];
  let field = "";
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    if (quoted) {
      if (character === '"' && text[index + 1] === '"') {
        field += '"';
        index += 1;
      } else if (character === '"') {
        quoted = false;
      } else {
        field += character;
      }
    } else if (character === '"' && field === "") {
      quoted = true;
    } else if (character === ",") {
      row.push(field);
      field = "";
    } else if (character === "\n" || character === "\r") {
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
  if (rows.length < 2) throw new Error("The CSV must contain a header and at least one holding.");
  if (rows.length > 1001) throw new Error("A CSV import is limited to 1000 rows.");

  const headers = rows[0].map((value) => value.trim().toLowerCase());
  const indexes = Object.fromEntries(Object.entries(REQUIRED_COLUMNS).map(([name, aliases]) => [
    name,
    aliases.map((alias) => headers.indexOf(alias)).find((index) => index >= 0) ?? -1,
  ]));
  for (const [name, index] of Object.entries(indexes)) {
    if (index < 0) throw new Error(`Required CSV column is missing: ${name}.`);
  }
  const currencyIndex = headers.indexOf("currency");
  const get = (cells, name) => String(cells[indexes[name]] || "").trim();
  const parseDecimal = (value, name, rowNumber, { positive = false, nonzero = false } = {}) => {
    if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(value)) {
      throw new Error(`Row ${rowNumber}: ${name} must be a plain decimal number.`);
    }
    const number = Number(value);
    if (!Number.isFinite(number) || (positive && number <= 0) || (nonzero && number === 0)) {
      throw new Error(`Row ${rowNumber}: ${name} is outside the accepted range.`);
    }
    return number;
  };
  const normalizeDate = (value, rowNumber) => {
    const parsed = Date.parse(value);
    if (!value || !Number.isFinite(parsed)) throw new Error(`Row ${rowNumber}: buy date is missing or invalid.`);
    return new Date(parsed).toISOString().slice(0, 10);
  };

  const lots = [];
  const seen = new Set();
  let duplicateCount = 0;
  const rejected = [];
  for (let index = 1; index < rows.length; index += 1) {
    const cells = rows[index];
    const rowNumber = index + 1;
    if (cells.length !== headers.length) {
      rejected.push({ rowNumber, reason: `Expected ${headers.length} fields, found ${cells.length}.` });
      continue;
    }
    try {
      const symbol = get(cells, "symbol").toUpperCase().replace(/\s+/g, "-");
      if (!/^[A-Z0-9][A-Z0-9.-]{0,29}$/.test(symbol)) throw new Error("symbol is invalid.");
      const quantity = parseDecimal(get(cells, "quantity"), "quantity", rowNumber, { nonzero: true });
      const buyPrice = parseDecimal(get(cells, "buyPrice"), "buy price", rowNumber, { positive: true });
      const boughtOn = normalizeDate(get(cells, "buyDate"), rowNumber);
      const sourceCurrency = currencyIndex >= 0 ? String(cells[currencyIndex] || "").trim().toUpperCase() : "";
      if (sourceCurrency && !/^[A-Z]{3}$/.test(sourceCurrency)) throw new Error("currency code is invalid.");
      const currency = sourceCurrency || missingCurrency || null;
      const currencySource = sourceCurrency ? "CSV" : currency ? "User selected" : "Missing";
      const key = JSON.stringify([symbol, quantity, buyPrice, boughtOn, currency]);
      if (seen.has(key)) {
        duplicateCount += 1;
        continue;
      }
      seen.add(key);
      lots.push({ symbol, quantity, buyPrice, boughtOn, currency, currencySource, sourceRow: rowNumber });
    } catch (error) {
      rejected.push({ rowNumber, reason: error.message });
    }
  }
  if (!lots.length) throw new Error("No valid, non-duplicate holdings were found.");
  return { lots, duplicateCount, rejected };
}

export function aggregateSellAdvisorHoldings(lots) {
  const grouped = new Map();
  for (const lot of lots || []) {
    const position = grouped.get(lot.symbol) || {
      symbol: lot.symbol,
      longQuantity: 0,
      shortQuantity: 0,
      longEntryValue: 0,
      shortEntryValue: 0,
      lots: [],
      currencies: new Set(),
      hasMissingCurrency: false,
      currencySources: new Set(),
    };
    if (lot.quantity > 0) {
      position.longQuantity += lot.quantity;
      position.longEntryValue += lot.quantity * lot.buyPrice;
    } else {
      position.shortQuantity += Math.abs(lot.quantity);
      position.shortEntryValue += Math.abs(lot.quantity) * lot.buyPrice;
    }
    if (lot.currency) position.currencies.add(lot.currency);
    else position.hasMissingCurrency = true;
    position.currencySources.add(lot.currencySource);
    position.lots.push(lot);
    grouped.set(lot.symbol, position);
  }
  return [...grouped.values()].map((position) => {
    const mixedDirection = position.longQuantity > 0 && position.shortQuantity > 0;
    const currency = position.currencies.size === 1 && !position.hasMissingCurrency
      ? [...position.currencies][0]
      : null;
    const quantity = position.longQuantity - position.shortQuantity;
    const buyPrice = mixedDirection
      ? null
      : position.longQuantity > 0
        ? position.longEntryValue / position.longQuantity
        : position.shortEntryValue / position.shortQuantity;
    const dates = position.lots
      .filter((lot) => (mixedDirection || Math.sign(lot.quantity) === Math.sign(quantity)))
      .map((lot) => lot.boughtOn)
      .sort();
    return {
      symbol: position.symbol,
      quantity,
      longQuantity: position.longQuantity,
      shortQuantity: position.shortQuantity,
      buyPrice,
      boughtOn: dates[0] || null,
      mixedDirection,
      currency,
      currencyStatus: currency ? "known" : position.currencies.size > 1 ? "mixed" : "missing",
      currencySource: [...position.currencySources].join(", "),
      lots: position.lots,
    };
  }).sort((left, right) => left.symbol.localeCompare(right.symbol));
}

function timestampValue(value) {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function selectLatestScanQuote(hourly, daily) {
  const candidates = [
    { ...hourly, source: "Hourly scan" },
    { ...daily, source: "Daily scan" },
  ].map((candidate) => ({
    ...candidate,
    price: Number(candidate?.price),
    timestamp: timestampValue(candidate?.at),
  })).filter((candidate) => Number.isFinite(candidate.price) && candidate.price > 0
    && candidate.timestamp !== null);
  candidates.sort((left, right) => right.timestamp - left.timestamp);
  return candidates[0]
    ? { ...candidates[0], at: new Date(candidates[0].timestamp).toISOString() }
    : null;
}

export function parseScannerReportTimestamp(title) {
  const match = /\b(\d{1,2})\/([A-Za-z]{3})\/(\d{4}),?\s+(\d{1,2}):(\d{2})\s+(EST|EDT)\b/i.exec(String(title || ""));
  if (!match) return null;
  const months = { jan: "01", feb: "02", mar: "03", apr: "04", may: "05", jun: "06", jul: "07", aug: "08", sep: "09", oct: "10", nov: "11", dec: "12" };
  const month = months[match[2].toLowerCase()];
  if (!month) return null;
  const offset = match[6].toUpperCase() === "EDT" ? "-04:00" : "-05:00";
  const value = `${match[3]}-${month}-${match[1].padStart(2, "0")}T${match[4].padStart(2, "0")}:${match[5]}:00${offset}`;
  return Number.isFinite(Date.parse(value)) ? new Date(value).toISOString() : null;
}
