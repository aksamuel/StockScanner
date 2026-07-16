from relative_strength import calculate_relative_strength
from watchlist import load_watchlist
from market_data import download_data
from indicators import calculate_indicators
from scoring import score_stock
from trade_plan import generate_trade_plan
from report import export_report
from ranking import rank_stocks
from signals import generate_signal
from charts import generate_stock_chart

# =====================================================
# AI STOCK SCANNER V3.1
# =====================================================

print("=" * 80)
print("                    AI STOCK SCANNER V3.1")
print("=" * 80)

# -----------------------------------------------------
# Load Watchlist
# -----------------------------------------------------
watchlist = load_watchlist()

print(f"Loaded {len(watchlist)} stocks")
print()

results = []

chart_data = {}

# =====================================================
# Scan Each Stock
# =====================================================

for _, row in watchlist.iterrows():

    symbol = row["Symbol"]
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

        if df.empty or len(df) < 200:
            print("Not enough historical data.")
            continue

    except Exception as e:
        print(f"Download Error : {e}")
        continue

    # -------------------------------------------------
    # Calculate Indicators
    # -------------------------------------------------

    try:
        df = calculate_indicators(df)
        latest = df.iloc[-1]

    except Exception as e:
        print(f"Indicator Error : {e}")
        continue

    # -------------------------------------------------
    # Relative Strength
    # -------------------------------------------------

    try:
        relative_strength = float(
            calculate_relative_strength(symbol)
        )
    except Exception as e:
        print(f"Relative Strength Error: {e}")
        relative_strength = 0.0

    # -------------------------------------------------
    # Score and signal
    # -------------------------------------------------
    
    score = score_stock(df, relative_strength)
    signal = generate_signal(df)
            
    # -------------------------------------------------
    # Calculate Score and signal
    # -------------------------------------------------

    score = score_stock(df, relative_strength)
    signal = generate_signal(df)

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

    plan = generate_trade_plan(
        df,
        available_cash=1000,
        risk_percent=1
    )
    
    # -------------------------------------------------
    # Store chart data
    # -------------------------------------------------
    
    chart_data[symbol] = {
        "data": df.copy(),
        "plan": plan
    }
    
    # -------------------------------------------------
    # Save Results
    # -------------------------------------------------

    results.append({

        "Symbol": symbol,
        "Market": market,
        "Sector": sector,
        "Priority": priority,

        "Current Price": round(latest["Close"], 2),

        "20 MA": round(latest["MA20"], 2),
        "50 MA": round(latest["MA50"], 2),
        "200 MA": round(latest["MA200"], 2),

        "RSI": round(latest["RSI"], 2),
        "MACD": round(latest["MACD"], 2),

        "Relative Strength": round(relative_strength, 2),

        "Score": score,
        "Recommendation": recommendation,

        "Signal": signal,
        
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

    # -------------------------------------------------
    # Display Results
    # -------------------------------------------------

    print(f"Market               : {market}")
    print(f"Sector               : {sector}")
    print(f"Priority             : {priority}")

    print()

    print(f"Current Price        : ${latest['Close']:.2f}")
    print(f"20-Day MA            : ${latest['MA20']:.2f}")
    print(f"50-Day MA            : ${latest['MA50']:.2f}")
    print(f"200-Day MA           : ${latest['MA200']:.2f}")

    print(f"RSI                  : {latest['RSI']:.2f}")
    print(f"MACD                 : {latest['MACD']:.2f}")
    print(f"Relative Strength    : {relative_strength:.2f}%")
    
    print()

    print(f"Profit-to-Time Score : {score}/100")
    print(f"Recommendation       : {recommendation}")
    print(f"AI Signal            : {signal}")
    
    print()

    print("Trend Analysis")
    print("-" * 35)

    print(f"Price > 200 MA       : {latest['Close'] > latest['MA200']}")
    print(f"20 MA > 50 MA        : {latest['MA20'] > latest['MA50']}")
    print(f"50 MA > 200 MA       : {latest['MA50'] > latest['MA200']}")

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

if len(results) > 0:

    print("Creating Excel Report...")

    ranked = rank_stocks(results)
    print()
    print("=" * 80)
    print("TOP OPPORTUNITIES")
    print("=" * 80)

    print(
        ranked[
            [
                "Rank",
                "Symbol",
                "Score",
                "Signal",
                "Recommendation",
                "Entry",
                "Target 1",
                "Risk/Reward"
            ]
        ].head(10).to_string(index=False)
    )

# =====================================================
# Generate Charts for Top 10 Opportunities
# =====================================================

    print()
    print("=" * 80)
    print("GENERATING TOP 10 CHARTS")
    print("=" * 80)

    top_symbols = ranked.head(10)["Symbol"].tolist()

    for symbol in top_symbols:

        stock_chart_data = chart_data.get(symbol)

    if stock_chart_data is not None:

        generate_stock_chart(
            symbol=symbol,
            df=stock_chart_data["data"],
            trade_plan=stock_chart_data["plan"]
        )

    else:
        print(f"Skipping {symbol} - No chart data")
        
# =====================================================
# Print scan summary  
# =====================================================

    print()
    print("=" * 80)
    print("SCAN SUMMARY")
    print("=" * 80)

    print(f"Stocks Scanned : {len(ranked)}")
    print(f"Strong Buy     : {(ranked['Recommendation'] == '🟢 STRONG BUY').sum()}")
    print(f"Buy            : {(ranked['Recommendation'] == '🟢 BUY').sum()}")
    print(f"Accumulate     : {(ranked['Recommendation'] == '🟡 ACCUMULATE').sum()}")
    print(f"Hold           : {(ranked['Recommendation'] == '🟡 HOLD').sum()}")
    print(f"Watch          : {(ranked['Recommendation'] == '🟠 WATCH').sum()}")
    print(f"Avoid          : {(ranked['Recommendation'] == '🔴 AVOID').sum()}")


# =====================================================
# Export Excel Report  
# =====================================================
    export_report(ranked.to_dict("records"))
    
else:

    print("No stocks were processed.")

print("=" * 80)
print("SCAN COMPLETED")
print("=" * 80)