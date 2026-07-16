import os

import matplotlib.pyplot as plt


CHART_FOLDER = "charts"


def generate_stock_chart(symbol, df, trade_plan):
    """
    Generate a technical chart for one stock.

    The chart includes:
    - Closing price
    - 20-day moving average
    - 50-day moving average
    - 200-day moving average
    - Suggested entry
    - Stop loss
    - Target 1
    """

    if df.empty:
        print(f"Chart skipped for {symbol}: no data.")
        return None

    required_columns = [
        "Close",
        "MA20",
        "MA50",
        "MA200",
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in df.columns
    ]

    if missing_columns:
        print(
            f"Chart skipped for {symbol}: "
            f"missing columns {missing_columns}"
        )
        return None

    os.makedirs(
        CHART_FOLDER,
        exist_ok=True
    )

    chart_data = df.tail(252).copy()

    entry_price = float(trade_plan["Entry"])
    stop_loss = float(trade_plan["Stop"])
    target_1 = float(trade_plan["Target1"])

    plt.figure(figsize=(14, 8))

    plt.plot(
        chart_data.index,
        chart_data["Close"],
        label="Close",
        linewidth=2
    )

    plt.plot(
        chart_data.index,
        chart_data["MA20"],
        label="20-day MA",
        linewidth=1.2
    )

    plt.plot(
        chart_data.index,
        chart_data["MA50"],
        label="50-day MA",
        linewidth=1.2
    )

    plt.plot(
        chart_data.index,
        chart_data["MA200"],
        label="200-day MA",
        linewidth=1.2
    )

    plt.axhline(
        entry_price,
        linestyle="--",
        linewidth=1.5,
        label=f"Entry: ${entry_price:.2f}"
    )

    plt.axhline(
        stop_loss,
        linestyle="--",
        linewidth=1.5,
        label=f"Stop: ${stop_loss:.2f}"
    )

    plt.axhline(
        target_1,
        linestyle="--",
        linewidth=1.5,
        label=f"Target 1: ${target_1:.2f}"
    )

    plt.title(
        f"{symbol} Technical Trade Plan",
        fontsize=16,
        fontweight="bold"
    )

    plt.xlabel("Date")
    plt.ylabel("Price (USD)")
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()

    filename = os.path.join(
        CHART_FOLDER,
        f"{symbol}.png"
    )

    plt.savefig(
        filename,
        dpi=150,
        bbox_inches="tight"
    )

    plt.close()

    print(f"Chart created: {filename}")

    return filename