from relative_strength import calculate_relative_strength
from watchlist import load_watchlist
from market_data import download_data
from indicators import calculate_indicators
from scoring import score_stock
from trade_plan import generate_trade_plan
from report import export_report
from ranking import rank_stocks
from signals import generate_signal

from Config import (
    MIN_PRICE,
    MIN_AVERAGE_DOLLAR_VOLUME,
    AVERAGE_VOLUME_DAYS,
)

# =====================================================
# AI STOCK SCANNER V3.2
# PHASE 2: PRICE AND LIQUIDITY FILTERS
# =====================================================

print("=" * 80)
print("              AI STOCK SCANNER V3.2 - LIQUIDITY FILTERS")
print("=" * 80)


# -----------------------------------------------------
# Load Watchlist
# -----------------------------------------------------

try:
    watchlist = load_watchlist()

except Exception as error:
    print(f"Could not load watchlist: {error}")
    raise SystemExit(1)


print(f"Loaded {len(watchlist)} stocks")
print(f"Minimum Price                : ${MIN_PRICE:,.2f}")
print(
    f"Minimum Average Dollar Volume: "
    f"${MIN_AVERAGE_DOLLAR_VOLUME:,.0f}"
)
print()


results = []

download_failed_count = 0
insufficient_data_count = 0
indicator_failed_count = 0
price_filtered_count = 0
liquidity_filtered_count = 0


# =====================================================
# Scan Each Stock
# =====================================================

for _, row in watchlist.iterrows():

    symbol = str(row["Symbol"]).strip()
    market = row["Market"]
    sector = row["Sector"]
    priority = row["Priority"]

    print("=" * 80)
    print(f"Scanning {symbol}")
    print("=" * 80)

    # -------------------------------------------------
    # Download Market Data
    # -------------------------------------------------

    try:
        df = download_data(symbol)

        if df is None or df.empty or len(df) < 200:
            print("Not enough historical data.")
            insufficient_data_count += 1
            continue

    except Exception as error:
        print(f"Download Error: {error}")
        download_failed_count += 1
        continue

    # -------------------------------------------------
    # Calculate Indicators
    # -------------------------------------------------

    try:
        df = calculate_indicators(df)
        latest = df.iloc[-1]

        current_price = float(latest["Close"])

        average_volume = float(
            df["Volume"]
            .tail(AVERAGE_VOLUME_DAYS)
            .mean()
        )

        average_dollar_volume = (
            current_price * average_volume
        )

    except Exception as error:
        print(f"Indicator Error: {error}")
        indicator_failed_count += 1
        continue

    # -------------------------------------------------
    # Phase 2: Minimum Price Filter
    # -------------------------------------------------

    if current_price < MIN_PRICE:
        print(
            f"Skipped: price ${current_price:.2f} is below "
            f"minimum price ${MIN_PRICE:.2f}."
        )

        price_filtered_count += 1
        continue

    # -------------------------------------------------
    # Phase 2: Liquidity Filter
    # -------------------------------------------------

    if average_dollar_volume < MIN_AVERAGE_DOLLAR_VOLUME:
        print(
            f"Skipped: {AVERAGE_VOLUME_DAYS}-day average "
            f"dollar volume ${average_dollar_volume:,.0f} "
            f"is below ${MIN_AVERAGE_DOLLAR_VOLUME:,.0f}."
        )

        liquidity_filtered_count += 1
        continue

    print(
        f"Liquidity Check       : PASSED "
        f"(${average_dollar_volume:,.0f})"
    )

    # -------------------------------------------------
    # Relative Strength
    # -------------------------------------------------

    try:
        relative_strength = float(
            calculate_relative_strength(symbol)
        )

    except Exception as error:
        print(f"Relative Strength Error: {error}")
        relative_strength = 0.0

    # -------------------------------------------------
    # Score and Signal
    # -------------------------------------------------

    try:
        score = score_stock(
            df,
            relative_strength
        )

        signal = generate_signal(df)

    except Exception as error:
        print(f"Score or Signal Error: {error}")
        continue

    # -------------------------------------------------
    # Recommendation
    # -------------------------------------------------

    if score >= 90:
        recommendation = "🟢 STRONG BUY"

    elif score >= 80:
        recommendation = "🟢 BUY"

    elif score >= 70:
        recommendation = "🟡 ACCUMULATE"

    elif score >= 60:
        recommendation = "🟡 HOLD"

    elif score >= 40:
        recommendation = "🟠 WATCH"

    else:
        recommendation = "🔴 AVOID"

    # -------------------------------------------------
    # Generate Trade Plan
    # -------------------------------------------------

    try:
        plan = generate_trade_plan(
            df,
            available_cash=1000,
            risk_percent=1
        )

    except Exception as error:
        print(f"Trade Plan Error: {error}")
        continue

    # -------------------------------------------------
    # Save Results
    # -------------------------------------------------

    results.append({

        "Symbol": symbol,
        "Market": market,
        "Sector": sector,
        "Priority": priority,

        "Current Price": round(
            current_price,
            2
        ),

        "Average Volume": round(
            average_volume,
            0
        ),

        "Average Dollar Volume": round(
            average_dollar_volume,
            0
        ),

        "Liquidity Status": "PASS",

        "20 MA": round(
            float(latest["MA20"]),
            2
        ),

        "50 MA": round(
            float(latest["MA50"]),
            2
        ),

        "200 MA": round(
            float(latest["MA200"]),
            2
        ),

        "RSI": round(
            float(latest["RSI"]),
            2
        ),

        "MACD": round(
            float(latest["MACD"]),
            2
        ),

        "Relative Strength": round(
            relative_strength,
            2
        ),

        "Score": score,
        "Recommendation": recommendation,
        "Signal": signal,

        "Trend": plan["Trend"],

        "Entry": round(
            float(plan["Entry"]),
            2
        ),

        "Stop Loss": round(
            float(plan["Stop"]),
            2
        ),

        "Target 1": round(
            float(plan["Target1"]),
            2
        ),

        "Target 2": round(
            float(plan["Target2"]),
            2
        ),

        "Target 3": round(
            float(plan["Target3"]),
            2
        ),

        "Risk/Reward": round(
            float(plan["RR"]),
            2
        ),

        "Suggested Shares": int(
            plan["Shares"]
        ),

        "Investment": round(
            float(plan["Investment"]),
            2
        )
    })

    # -------------------------------------------------
    # Display Results
    # -------------------------------------------------

    print(f"Market               : {market}")
    print(f"Sector               : {sector}")
    print(f"Priority             : {priority}")

    print()

    print(f"Current Price        : ${current_price:.2f}")
    print(f"Average Volume       : {average_volume:,.0f}")
    print(
        f"Average Dollar Volume: "
        f"${average_dollar_volume:,.0f}"
    )

    print()

    print(f"20-Day MA            : ${latest['MA20']:.2f}")
    print(f"50-Day MA            : ${latest['MA50']:.2f}")
    print(f"200-Day MA           : ${latest['MA200']:.2f}")

    print(f"RSI                  : {latest['RSI']:.2f}")
    print(f"MACD                 : {latest['MACD']:.2f}")
    print(
        f"Relative Strength    : "
        f"{relative_strength:.2f}%"
    )

    print()

    print(f"Profit-to-Time Score : {score}/100")
    print(f"Recommendation       : {recommendation}")
    print(f"AI Signal            : {signal}")

    print()

    print("Trend Analysis")
    print("-" * 35)

    print(
        f"Price > 200 MA       : "
        f"{current_price > float(latest['MA200'])}"
    )

    print(
        f"20 MA > 50 MA        : "
        f"{float(latest['MA20']) > float(latest['MA50'])}"
    )

    print(
        f"50 MA > 200 MA       : "
        f"{float(latest['MA50']) > float(latest['MA200'])}"
    )

    print()

    print("Trade Plan")
    print("-" * 35)

    print(f"Trend                : {plan['Trend']}")
    print(f"Suggested Entry      : ${plan['Entry']:.2f}")
    print(f"Stop Loss            : ${plan['Stop']:.2f}")
    print(f"Target 1             : ${plan['Target1']:.2f}")
    print(f"Target 2             : ${plan['Target2']:.2f}")
    print(f"Target 3             : ${plan['Target3']:.2f}")
    print(f"Risk / Reward        : {plan['RR']:.2f}")
    print(f"Suggested Shares     : {plan['Shares']}")
    print(f"Investment           : ${plan['Investment']:.2f}")

    print()


# =====================================================
# Export Report
# =====================================================

print("=" * 80)

if results:

    print("Creating Excel Report...")

    ranked = rank_stocks(results)

    print()
    print("=" * 80)
    print("TOP OPPORTUNITIES")
    print("=" * 80)

    display_columns = [
        "Rank",
        "Symbol",
        "Current Price",
        "Average Dollar Volume",
        "Score",
        "Signal",
        "Recommendation",
        "Entry",
        "Target 1",
        "Risk/Reward"
    ]

    available_columns = [
        column
        for column in display_columns
        if column in ranked.columns
    ]

    print(
        ranked[
            available_columns
        ].head(10).to_string(index=False)
    )

    # -------------------------------------------------
    # Scan Summary
    # -------------------------------------------------

    print()
    print("=" * 80)
    print("SCAN SUMMARY")
    print("=" * 80)

    print(f"Watchlist Stocks       : {len(watchlist)}")
    print(f"Stocks Passing Filters : {len(ranked)}")
    print(f"Price Filtered         : {price_filtered_count}")
    print(f"Liquidity Filtered     : {liquidity_filtered_count}")
    print(f"Insufficient Data      : {insufficient_data_count}")
    print(f"Download Failures      : {download_failed_count}")
    print(f"Indicator Failures     : {indicator_failed_count}")

    print()

    print(
        "Strong Buy             : "
        f"{(ranked['Recommendation'] == '🟢 STRONG BUY').sum()}"
    )

    print(
        "Buy                    : "
        f"{(ranked['Recommendation'] == '🟢 BUY').sum()}"
    )

    print(
        "Accumulate             : "
        f"{(ranked['Recommendation'] == '🟡 ACCUMULATE').sum()}"
    )

    print(
        "Hold                   : "
        f"{(ranked['Recommendation'] == '🟡 HOLD').sum()}"
    )

    print(
        "Watch                  : "
        f"{(ranked['Recommendation'] == '🟠 WATCH').sum()}"
    )

    print(
        "Avoid                  : "
        f"{(ranked['Recommendation'] == '🔴 AVOID').sum()}"
    )

    # -------------------------------------------------
    # Export Excel Report
    # -------------------------------------------------

    export_report(
        ranked.to_dict("records")
    )

else:

    print("No stocks passed the price and liquidity filters.")

    print()
    print(f"Watchlist Stocks   : {len(watchlist)}")
    print(f"Price Filtered     : {price_filtered_count}")
    print(f"Liquidity Filtered : {liquidity_filtered_count}")
    print(f"Insufficient Data  : {insufficient_data_count}")
    print(f"Download Failures  : {download_failed_count}")


print("=" * 80)
print("SCAN COMPLETED")
print("=" * 80)