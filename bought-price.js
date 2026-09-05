const priceFormat = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 2, maximumFractionDigits: 2,
});

function groupBySymbol(rows) {
  const groups = new Map();
  for (const row of rows) {
    const symbol = String(row.symbol || "").trim().toUpperCase();
    if (!symbol) continue;
    if (!groups.has(symbol)) groups.set(symbol, []);
    groups.get(symbol).push(row);
  }
  return groups;
}

export function purchaseBasisBySymbol(selections = [], holdings = []) {
  const groups = groupBySymbol(selections);
  const portfolio = groupBySymbol(holdings);
  // Portfolio lots take precedence: a saved bought-list entry may describe
  // the same position and must not be counted as an additional purchase.
  for (const [symbol, rows] of portfolio) groups.set(symbol, rows);
  const result = new Map();
  for (const [symbol, rows] of groups) {
    const source = portfolio.has(symbol) ? "portfolio" : "bought list";
    const currencies = new Set(rows.map(row => String(row.currency || "USD").toUpperCase()));
    const currency = currencies.size === 1 ? [...currencies][0] : null;
    let reason = "";
    if (!currency) reason = "Holdings use different currencies; there is no single comparable buy price.";
    else if (rows.some(row => !(Number(row.quantity) > 0) || !Number.isFinite(Number(row.quantity)))) {
      reason = "A buy-price comparison requires long positions with valid quantities.";
    } else if (rows.some(row => !(Number(row.buy_price) > 0) || !Number.isFinite(Number(row.buy_price)))) {
      reason = "A valid buy price is needed for every lot.";
    }
    const quantity = rows.reduce((sum, row) => sum + Number(row.quantity), 0);
    const cost = rows.reduce((sum, row) => sum + Number(row.quantity) * Number(row.buy_price), 0);
    const price = reason ? null : cost / quantity;
    if (!reason && (!Number.isFinite(price) || !(price > 0))) reason = "Buy price is unavailable.";
    result.set(symbol, {
      price: reason ? null : price, currency, reason, source, lots: rows.length,
    });
  }
  return result;
}

export function levelReturn(level, basis) {
  if (!(Number(level) > 0) || !Number.isFinite(Number(level))) return null;
  if (!(basis?.price > 0) || basis.currency !== "USD") return null;
  const percent = ((Number(level) - basis.price) / basis.price) * 100;
  if (!Number.isFinite(percent)) return null;
  const rounded = Math.round(percent * 100) / 100;
  return {
    text: `${rounded > 0 ? "+" : ""}${rounded.toFixed(2)}%`,
    tone: rounded > 0 ? "profit" : rounded < 0 ? "loss" : "neutral",
  };
}

export function annotateBoughtAnalysis(bases, page, root = document) {
  const columns = page === "technical.html"
    ? ["Target 1", "Target 2", "Target 3"]
    : page === "analysts.html"
      ? ["Support Low", "Support High", "Resistance Low", "Resistance High"] : [];
  if (!columns.length) return;

  if (!root.querySelector("style[data-bought-prices]")) {
    const style = root.createElement("style");
    style.dataset.boughtPrices = "";
    style.textContent = `
      .bought-level-return {
        display: block; width: max-content; margin-top: 5px; padding: 2px 7px;
        border: 1px solid; border-radius: 999px; font-size: .72rem;
        line-height: 1.4; font-weight: 700; white-space: nowrap;
      }
      .bought-level-profit { color: #b9f6ca; background: #1b5e20; border-color: #66bb6a; }
      .bought-level-loss { color: #ffcdd2; background: #8e2020; border-color: #ef9a9a; }
      .bought-level-neutral { color: #cfd8dc; background: #37474f; border-color: #90a4ae; }
      .bought-price-note { color: #b0bec5; font-size: .82rem; line-height: 1.5; }
    `;
    root.head.appendChild(style);
  }

  const cells = new Map();
  function renderReturn(cell, basis) {
    const comparison = levelReturn(cell.dataset.priceLevel, basis);
    const level = Number(cell.dataset.priceLevel);
    const previous = cell.querySelector(".bought-level-return");
    if (!(level > 0) || !Number.isFinite(level)) {
      previous?.remove();
      return;
    }
    const text = comparison?.text || "Return unavailable";
    const tone = comparison?.tone || "neutral";
    const className = `bought-level-return bought-level-${tone}`;
    if (previous?.textContent === text && previous.className === className) return;
    const badge = previous || root.createElement("span");
    badge.className = className;
    badge.textContent = text;
    badge.title = comparison
      ? `${text} from your buy price, before fees, taxes, dividends and currency conversion.`
      : basis.reason || "The report's USD price cannot be compared with a buy price in another currency.";
    if (!previous) cell.appendChild(badge);
  }

  root.querySelectorAll("#topTable, #allTable").forEach(table => {
    const headers = [...table.querySelectorAll("thead th")].map(th => th.textContent.trim());
    const symbolIndex = headers.indexOf("Symbol");
    if (symbolIndex < 0) return;
    const levelIndices = columns.map(name => headers.indexOf(name)).filter(index => index >= 0);
    table.querySelectorAll("tbody tr").forEach(row => {
      const symbol = (row.dataset.symbol || row.querySelector(".symbol-name")?.textContent || "").trim().toUpperCase();
      const basis = bases.get(symbol);
      if (!basis) return;
      const symbolCell = row.cells[symbolIndex];
      if (!symbolCell) return;
      const badge = symbolCell.querySelector(".already-bought-badge") || root.createElement("span");
      badge.className = "already-bought-badge";
      const price = basis.price === null ? "unavailable"
        : `${basis.currency === "USD" ? "$" : `${basis.currency} `}${priceFormat.format(basis.price)}`;
      badge.textContent = `Bought @ ${price}`;
      badge.title = basis.reason || (basis.lots > 1
        ? `Quantity-weighted average buy price across ${basis.lots} ${basis.source} lots.`
        : `Buy price from your ${basis.source}.`);
      if (!badge.parentNode) symbolCell.append(" ", badge);
      for (const index of levelIndices) {
        const cell = row.cells[index];
        if (!cell) continue;
        cells.set(cell, basis);
        renderReturn(cell, basis);
      }
    });
  });

  if (cells.size && !root.querySelector(".bought-price-note")) {
    const note = root.createElement("p");
    note.className = "bought-price-note";
    note.textContent = "Bought @ shows your purchase price (quantity-weighted average for multiple lots). Labels below price levels show the change from that buy price: green for profit, red for loss, grey for breakeven or unavailable. Fees, taxes, dividends and currency conversion are excluded.";
    root.querySelector(".filter-bar")?.after(note);
  }

  // Refresh Latest Prices rebuilds price cells to update their direction arrows.
  // Restore the purchase-return label without changing those arrows or prices.
  const observer = new MutationObserver(mutations => {
    const changed = new Set();
    for (const mutation of mutations) {
      const element = mutation.target.nodeType === 1 ? mutation.target : mutation.target.parentElement;
      const cell = element?.closest("td");
      if (cells.has(cell)) changed.add(cell);
    }
    changed.forEach(cell => renderReturn(cell, cells.get(cell)));
  });
  cells.forEach((_, cell) => observer.observe(cell, {
    childList: true, subtree: true, attributes: true, attributeFilter: ["data-price-level"],
  }));
}
