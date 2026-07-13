from watchlist import WATCHLIST
from market_data import download_data
from indicators import calculate_indicators
from scoring import score_stock
from trade_plan import generate_trade_plan
from report import export_report

print("=" * 80)
print("                         AI STOCK SCANNER")
print("=" * 80)

# Store results for Excel export
results = []

# ==================================================
# Scan each stock
# ==================================================
for symbol in WATCHLIST:

    print(f"\nScanning {symbol}...")

    # Download Data
    df = download_data(symbol)

    # Skip if insufficient data
    if df.empty or len(df) < 200:
        print(f"Skipping {symbol} (Not enough historical data)")
        continue

    # Calculate Indicators
    df = calculate_indicators(df)

    latest = df.iloc[-1]

    # Calculate Score
    score = score_stock(df)

    # Recommendation
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

    # Generate Trade Plan
    plan = generate_trade_plan(
        df,
        available_cash=10000,
        risk_percent=1
    )

    # Save results for Excel
    results.append({
        "Symbol": symbol,
        "Current Price": round(latest["Close"], 2),
        "20 MA": round(latest["MA20"], 2),
        "50 MA": round(latest["MA50"], 2),
        "200 MA": round(latest["MA200"], 2),
        "RSI": round(latest["RSI"], 2),
        "MACD": round(latest["MACD"], 2),
        "Score": score,
        "Recommendation": recommendation,
        "Trend": plan["Trend"],
        "Entry": round(plan["Entry"], 2),
        "Stop Loss": round(plan["Stop"], 2),
        "Target 1": round(plan["Target1"], 2),
        "Target 2": round(plan["Target2"], 2),
        "Target 3": round(plan["Target3"], 2),
        "Risk/Reward": round(plan["RR"], 2),
        "Suggested Shares": plan["Shares"],
        "Investment": round(plan["Investment"], 2)
    })

    # Display Results
    print("-" * 80)
    print(f"Stock                : {symbol}")
    print("-" * 80)
    print(f"Current Price        : ${latest['Close']:.2f}")
    print(f"20-Day MA            : ${latest['MA20']:.2f}")
    print(f"50-Day MA            : ${latest['MA50']:.2f}")
    print(f"200-Day MA           : ${latest['MA200']:.2f}")
    print(f"RSI                  : {latest['RSI']:.2f}")
    print(f"MACD                 : {latest['MACD']:.2f}")

    print()
    print(f"Profit-to-Time Score : {score}/100")
    print(f"Recommendation       : {recommendation}")

    print()
    print("Trend Analysis")
    print("-" * 30)
    print(f"Price > 200 MA       : {latest['Close'] > latest['MA200']}")
    print(f"20 MA > 50 MA        : {latest['MA20'] > latest['MA50']}")
    print(f"50 MA > 200 MA       : {latest['MA50'] > latest['MA200']}")

    print()
    print("Trade Plan")
    print("-" * 30)
    print(f"Trend                : {plan['Trend']}")
    print(f"Suggested Entry      : ${plan['Entry']:.2f}")
    print(f"Stop Loss            : ${plan['Stop']:.2f}")
    print(f"Target 1             : ${plan['Target1']:.2f}")
    print(f"Target 2             : ${plan['Target2']:.2f}")
    print(f"Target 3             : ${plan['Target3']:.2f}")
    print(f"Risk / Reward        : {plan['RR']:.2f}")
    print(f"Suggested Shares     : {plan['Shares']}")
    print(f"Investment           : ${plan['Investment']:.2f}")

# ==================================================
# Export to Excel
# ==================================================
print("\nCreating Excel report...")
export_report(results)

print("=" * 80)
print("SCAN COMPLETED")
print("=" * 80)