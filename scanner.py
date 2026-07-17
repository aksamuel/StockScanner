from charts import generate_stock_chart
from indicators import calculate_indicators
from market_data import download_data
from ranking import rank_stocks
from relative_strength import calculate_relative_strength
from report import export_report
from scoring import score_stock
from signals import generate_signal
from trade_plan import generate_trade_plan

from config import (
    AVAILABLE_CASH,
    RISK_PER_TRADE,
    TOP_RESULTS,
    MAX_STOCKS,
    MIN_PRICE,
    MIN_AVERAGE_DOLLAR_VOLUME
)

from watchlist import load_watchlist

def get_recommendation(score):
    """Convert the numeric score into a recommendation."""

    if score >= 90:
        return "🟢 STRONG BUY"

    if score >= 80:
        return "🟢 BUY"

    if score >= 70:
        return "🟡 ACCUMULATE"

    if score >= 60:
        return "🟡 HOLD"

    if score >= 40:
        return "🟠 WATCH"

    return "🔴 AVOID"


def process_stock(row):
    """
    Download, analyze, score and prepare one stock.

    Returns:
        tuple:
            result dictionary,
            historical DataFrame,
            trade-plan dictionary

        Returns None when the stock cannot be processed.
    """

    symbol = str(row["Symbol"]).strip().upper()
    market = row["Market"]
    sector = row["Sector"]
    priority = row["Priority"]

    print("=" * 80)
    print(f"Scanning {symbol}")
    print("=" * 80)

    # Download historical data
    try:
        df = download_data(symbol)
    except Exception as error:
        print(f"Download error for {symbol}: {error}")
        return None

    if df is None or df.empty:
        print(f"Skipping {symbol}: no historical data.")
        return None

    if len(df) < 200:
        print(
            f"Skipping {symbol}: only {len(df)} trading days "
            "are available."
        )
        return None

    # Calculate technical indicators
    try:
        df = calculate_indicators(df)
        latest = df.iloc[-1]
#-------
        current_price = float(latest["Close"])

        average_volume = float(
            df["Volume"].tail(20).mean()
        )

        average_dollar_volume = (
            current_price * average_volume
        )

        if current_price < MIN_PRICE:
            print(
                f"Skipping {symbol}: price "
                f"${current_price:.2f} is below minimum."
            )
            return None

        if average_dollar_volume < MIN_AVERAGE_DOLLAR_VOLUME:
            print(
                f"Skipping {symbol}: average dollar volume "
                f"${average_dollar_volume:,.0f} is too low."
            )
            return None
    
#-----------    
    except Exception as error:
        print(f"Indicator error for {symbol}: {error}")
        return None

    # Calculate relative strength
    try:
        relative_strength = float(
            calculate_relative_strength(symbol)
        )
    except Exception as error:
        print(f"Relative-strength error for {symbol}: {error}")
        relative_strength = 0.0

    # Calculate score and signal
    try:
        score = int(
            score_stock(
                df,
                relative_strength
            )
        )

        signal = generate_signal(df)

    except Exception as error:
        print(f"Scoring or signal error for {symbol}: {error}")
        return None

    recommendation = get_recommendation(score)

    # Generate trade plan
    try:
        plan = generate_trade_plan(
            df,
            available_cash=AVAILABLE_CASH,
            risk_percent=RISK_PER_TRADE
        )
    except Exception as error:
        print(f"Trade-plan error for {symbol}: {error}")
        return None

    result = {
        "Symbol": symbol,
        "Market": market,
        "Sector": sector,
        "Priority": priority,

        "Current Price": round(
            float(latest["Close"]),
            2
        ),

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
        ),
#---------
        
        "Average Volume": round(
            average_volume,
            0
        ),
        
        "Average Dollar Volume": round(
            average_dollar_volume,
            0
        ),
#---------
    }

    display_stock_result(result)

    return result, df.copy(), plan


def display_stock_result(result):
    """Print the analysis for one stock."""

    print(f"Market               : {result['Market']}")
    print(f"Sector               : {result['Sector']}")
    print(f"Priority             : {result['Priority']}")
    print()

    print(
        f"Current Price        : "
        f"${result['Current Price']:.2f}"
    )

    print(
        f"20-Day MA            : "
        f"${result['20 MA']:.2f}"
    )

    print(
        f"50-Day MA            : "
        f"${result['50 MA']:.2f}"
    )

    print(
        f"200-Day MA           : "
        f"${result['200 MA']:.2f}"
    )

    print(f"RSI                  : {result['RSI']:.2f}")
    print(f"MACD                 : {result['MACD']:.2f}")

    print(
        f"Relative Strength    : "
        f"{result['Relative Strength']:.2f}%"
    )

    print()
    print(
        f"Profit-to-Time Score : "
        f"{result['Score']}/100"
    )

    print(
        f"Recommendation       : "
        f"{result['Recommendation']}"
    )

    print(
        f"AI Signal            : "
        f"{result['Signal']}"
    )

    print()
    print("Trade Plan")
    print("-" * 35)

    print(
        f"Trend                : "
        f"{result['Trend']}"
    )

    print(
        f"Suggested Entry      : "
        f"${result['Entry']:.2f}"
    )

    print(
        f"Stop Loss            : "
        f"${result['Stop Loss']:.2f}"
    )

    print(
        f"Target 1             : "
        f"${result['Target 1']:.2f}"
    )

    print(
        f"Target 2             : "
        f"${result['Target 2']:.2f}"
    )

    print(
        f"Target 3             : "
        f"${result['Target 3']:.2f}"
    )

    print(
        f"Risk / Reward        : "
        f"{result['Risk/Reward']:.2f}"
    )

    print(
        f"Suggested Shares     : "
        f"{result['Suggested Shares']}"
    )

    print(
        f"Investment           : "
        f"${result['Investment']:.2f}"
    )

    print()

def display_top_opportunities(ranked):
    """Print the highest-ranked stocks."""

    columns = [
        "Rank",
        "Symbol",
        "Score",
        "Signal",
        "Recommendation",
        "Entry",
        "Target 1",
        "Risk/Reward"
    ]

    available_columns = [
        column
        for column in columns
        if column in ranked.columns
    ]

    print()
    print("=" * 80)
    print("TOP OPPORTUNITIES")
    print("=" * 80)

    print(
        ranked[
            available_columns
        ].head(TOP_RESULTS).to_string(
            index=False
        )
    )


def display_scan_summary(ranked):
    """Print recommendation totals."""

    print()
    print("=" * 80)
    print("SCAN SUMMARY")
    print("=" * 80)

    print(f"Stocks Scanned : {len(ranked)}")

    recommendations = ranked["Recommendation"]

    print(
        "Strong Buy     : "
        f"{(recommendations == '🟢 STRONG BUY').sum()}"
    )

    print(
        "Buy            : "
        f"{(recommendations == '🟢 BUY').sum()}"
    )

    print(
        "Accumulate     : "
        f"{(recommendations == '🟡 ACCUMULATE').sum()}"
    )

    print(
        "Hold           : "
        f"{(recommendations == '🟡 HOLD').sum()}"
    )

    print(
        "Watch          : "
        f"{(recommendations == '🟠 WATCH').sum()}"
    )

    print(
        "Avoid          : "
        f"{(recommendations == '🔴 AVOID').sum()}"
    )


def create_top_charts(ranked, chart_data):
    """Generate charts for the highest-ranked stocks."""

    print()
    print("=" * 80)
    print("GENERATING TOP CHARTS")
    print("=" * 80)

    top_symbols = (
        ranked.head(TOP_RESULTS)["Symbol"]
        .astype(str)
        .tolist()
    )

    for symbol in top_symbols:
        stored_data = chart_data.get(symbol)

        if stored_data is None:
            print(f"No chart data available for {symbol}")
        else:
            try:
                generate_stock_chart(
                    symbol=symbol,
                    df=stored_data["data"],
                    trade_plan=stored_data["plan"]
                )
            except Exception as error:
                print(
                    f"Chart-generation error for "
                    f"{symbol}: {error}"
                )


def main():
    """Run the complete stock-scanner workflow."""

    print("=" * 80)
    print("                    AI STOCK SCANNER V4.4")
    print("=" * 80)

    try:
        watchlist = load_watchlist()
        
        if MAX_STOCKS is not None:
            watchlist = watchlist.head(MAX_STOCKS)
    
    except Exception as error:
        print(f"Could not load the watchlist: {error}")
        return

    if watchlist.empty:
        print("The watchlist contains no enabled stocks.")
        return

    print(f"Loaded {len(watchlist)} stocks")
    print()

    results = []
    chart_data = {}
    processed_count = 0
    skipped_count = 0

    for _, row in watchlist.iterrows():

        processed = process_stock(row)

        if processed is None:
            skipped_count += 1
            continue

        processed_count += 1

        result, df, plan = processed

        results.append(result)
        chart_data[result["Symbol"]] = {
            "data": df,
            "plan": plan
        }

    print()
    print("=" * 80)
    print("PROCESSING SUMMARY")
    print("=" * 80)
    print(f"Successfully processed : {processed_count}")
    print(f"Skipped stocks         : {skipped_count}")

    if not results:
        print("No stocks were processed successfully.")
        return

    ranked = rank_stocks(results)

    display_top_opportunities(ranked)
    display_scan_summary(ranked)

    create_top_charts(
        ranked,
        chart_data
    )

    print()
    print("=" * 80)
    print("CREATING EXCEL REPORT")
    print("=" * 80)

    try:
        report_filename = export_report(
            ranked.to_dict("records")
        )

        if report_filename:
            print(f"Report saved to: {report_filename}")

    except Exception as error:
        print(f"Excel-report error: {error}")

    print()
    print("=" * 80)
    print("SCAN COMPLETED")
    print("=" * 80)


if __name__ == "__main__":
    main()