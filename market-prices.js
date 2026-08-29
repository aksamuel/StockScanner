const SVG_NS = "http://www.w3.org/2000/svg";

export function marketRows(snapshot) {
  const hourly = snapshot?.prices || {};
  const daily = snapshot?.daily_prices || {};
  return [...new Set([...Object.keys(hourly), ...Object.keys(daily)])]
    .sort()
    .map((symbol) => {
      const hourlyPrice = Number(hourly[symbol]);
      const dailyPrice = Number(daily[symbol]);
      const hasHourly = Number.isFinite(hourlyPrice) && hourlyPrice > 0;
      const hasDaily = Number.isFinite(dailyPrice) && dailyPrice > 0;
      return {
        symbol,
        hourlyPrice: hasHourly ? hourlyPrice : null,
        dailyPrice: hasDaily ? dailyPrice : null,
        changePercent: hasHourly && hasDaily
          ? ((hourlyPrice - dailyPrice) / dailyPrice) * 100
          : null,
      };
    });
}

export function intradayPoints(snapshot, symbol) {
  const dailyPrice = Number(snapshot?.daily_prices?.[symbol]);
  const points = Array.isArray(snapshot?.intraday_series?.[symbol])
    ? snapshot.intraday_series[symbol]
    : [];
  return points
    .map((point) => ({
      timestamp: point?.timestamp,
      price: Number(point?.price),
    }))
    .filter((point) => point.timestamp && Number.isFinite(point.price) && point.price > 0)
    .sort((left, right) => left.timestamp.localeCompare(right.timestamp))
    .map((point) => ({
      ...point,
      changePercent: Number.isFinite(dailyPrice) && dailyPrice > 0
        ? ((point.price - dailyPrice) / dailyPrice) * 100
        : null,
    }));
}

function svgElement(name, attributes = {}) {
  const element = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, value);
  return element;
}

export function drawSpikeChart(svg, points, dailyPrice, formatPrice) {
  svg.replaceChildren();
  const width = 900;
  const height = 320;
  const margin = { top: 24, right: 24, bottom: 54, left: 64 };
  const innerWidth = width - margin.left - margin.right;
  const innerHeight = height - margin.top - margin.bottom;
  const changes = points.map((point) => point.changePercent).filter(Number.isFinite);

  if (!points.length || !changes.length) {
    const label = svgElement("text", { x: width / 2, y: height / 2, class: "chart-empty", "text-anchor": "middle" });
    label.textContent = "Intraday points will appear after the hourly updater runs.";
    svg.append(label);
    return;
  }

  const extent = Math.max(0.25, ...changes.map((value) => Math.abs(value))) * 1.15;
  const y = (value) => margin.top + ((extent - value) / (extent * 2)) * innerHeight;
  const zeroY = y(0);
  const slotWidth = innerWidth / points.length;
  const barWidth = Math.max(8, Math.min(54, slotWidth * 0.58));

  const baseline = svgElement("line", {
    x1: margin.left, x2: width - margin.right, y1: zeroY, y2: zeroY, class: "chart-baseline",
  });
  svg.append(baseline);

  for (const value of [extent, 0, -extent]) {
    const label = svgElement("text", { x: margin.left - 10, y: y(value) + 4, class: "chart-axis-label", "text-anchor": "end" });
    label.textContent = `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
    svg.append(label);
  }

  points.forEach((point, index) => {
    const value = point.changePercent;
    const x = margin.left + slotWidth * index + (slotWidth - barWidth) / 2;
    const endY = y(value);
    const rect = svgElement("rect", {
      x, y: Math.min(zeroY, endY), width: barWidth,
      height: Math.max(2, Math.abs(zeroY - endY)),
      class: value >= 0 ? "spike-positive" : "spike-negative",
      tabindex: "0",
      role: "img",
      "aria-label": `${new Date(point.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}: ${formatPrice(point.price)}, ${value >= 0 ? "+" : ""}${value.toFixed(2)} percent versus daily close`,
    });
    const title = svgElement("title");
    title.textContent = rect.getAttribute("aria-label");
    rect.append(title);
    svg.append(rect);

    const timeLabel = svgElement("text", {
      x: x + barWidth / 2, y: height - margin.bottom + 22,
      class: "chart-axis-label", "text-anchor": "middle",
    });
    timeLabel.textContent = new Date(point.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    svg.append(timeLabel);
  });

  const closeLabel = svgElement("text", { x: width - margin.right, y: 16, class: "chart-close-label", "text-anchor": "end" });
  closeLabel.textContent = `Daily close: ${formatPrice(dailyPrice)}`;
  svg.append(closeLabel);
}
