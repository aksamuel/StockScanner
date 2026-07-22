from concurrent.futures import ThreadPoolExecutor, as_completed

from stockscanner.config import (
    MIN_PRICE,
    MIN_AVERAGE_DOLLAR_VOLUME,
    AVERAGE_VOLUME_DAYS,
)
from stockscanner.universe import load_nyse_tickers
from stockscanner.watchlist import load_watchlist
from stockscanner.market_data import download_data
from stockscanner.indicators import calculate_indicators
from stockscanner.scoring import score_stock
from stockscanner.trade_plan import generate_trade_plan
from stockscanner.report import export_report
from stockscanner.ranking import rank_stocks
from stockscanner.signals import generate_signal
from stockscanner.relative_strength import calculate_relative_strength


def get_recommendation(score):
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
    symbol = str(row.get("Symbol", "")).strip().upper()
    market = row.get("Market", "Unknown")
    sector = row.get("Sector", "Unknown")
    priority = row.get("Priority", "Normal")

    print("=" * 80)
    print(f"Scanning {symbol}")
    print("=" * 80)

    try:
        df = download_data(symbol)
    except Exception as error:
        print(f"Download Error: {error}")
        return None

    if df is None or df.empty or len(df) < 200:
        print("Not enough historical data.")
        return None

    try:
        df = calculate_indicators(df)
        latest = df.iloc[-1]

        current_price = float(latest["Close"])
        average_volume = float(df["Volume"].tail(AVERAGE_VOLUME_DAYS).mean())
        average_dollar_volume = current_price * average_volume
    except Exception as error:
        print(f"Indicator Error: {error}")
        return None

    if current_price < MIN_PRICE:
        print("Skipped: price below minimum price.")
        return None

    if average_dollar_volume < MIN_AVERAGE_DOLLAR_VOLUME:
        print("Skipped: dollar volume below threshold.")
        return None

    print(f"Liquidity Check       : PASSED (${average_dollar_volume:,.0f})")

    try:
        relative_strength = float(calculate_relative_strength(symbol))
    except Exception as error:
        print(f"Relative Strength Error: {error}")
        relative_strength = 0.0

    try:
        score = score_stock(df, relative_strength)
        signal = generate_signal(df)
    except Exception as error:
        print(f"Score or Signal Error: {error}")
        return None

    recommendation = get_recommendation(score)

    try:
        plan = generate_trade_plan(df, available_cash=1000, risk_percent=1)
    except Exception as error:
        print(f"Trade Plan Error: {error}")
        return None

    result = {
        "Symbol": symbol,
        "Market": market,
        "Sector": sector,
        "Priority": priority,
        "Current Price": round(current_price, 2),
        "Average Volume": round(average_volume, 0),
        "Average Dollar Volume": round(average_dollar_volume, 0),
        "Liquidity Status": "PASS",
        "20 MA": round(float(latest["MA20"]), 2),
        "50 MA": round(float(latest["MA50"]), 2),
        "200 MA": round(float(latest["MA200"]), 2),
        "RSI": round(float(latest["RSI"]), 2),
        "MACD": round(float(latest["MACD"]), 2),
        "Relative Strength": round(relative_strength, 2),
        "Score": score,
        "Recommendation": recommendation,
        "Signal": signal,
        "Trend": plan["Trend"],
        "Entry": round(float(plan["Entry"]), 2),
        "Stop Loss": round(float(plan["Stop"]), 2),
        "Target 1": round(float(plan["Target1"]), 2),
        "Target 2": round(float(plan["Target2"]), 2),
        "Target 3": round(float(plan["Target3"]), 2),
        "Risk/Reward": round(float(plan["RR"]), 2),
        "Suggested Shares": int(plan["Shares"]),
        "Investment": round(float(plan["Investment"]), 2),
    }

    print(f"Recommendation       : {recommendation}")
    print()

    return result


def scan_universe(stock_df, export_to_excel=True, parallel=False, max_workers=10):
    if parallel:
        return scan_universe_parallel(stock_df, export_to_excel=export_to_excel, max_workers=max_workers)

    print("=" * 80)
    print("              AI STOCK SCANNER V3.2 - LIQUIDITY FILTERS")
    print("=" * 80)

    print(f"Loaded {len(stock_df)} stocks")
    print(f"Minimum Price                : ${MIN_PRICE:,.2f}")
    print()

    results = []
    download_failed_count = 0
    insufficient_data_count = 0
    indicator_failed_count = 0
    price_filtered_count = 0
    liquidity_filtered_count = 0

    for _, row in stock_df.iterrows():
        result = process_stock(row)
        if result is None:
            continue
        results.append(result)

    print("=" * 80)

    if results:
        print("Creating Excel Report...")
        ranked = rank_stocks(results)
        if export_to_excel:
            export_report(ranked.to_dict("records"))
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
            "Risk/Reward",
        ]

        available_columns = [column for column in display_columns if column in ranked.columns]
        print(ranked[available_columns].head(10).to_string(index=False))

        print()
        print("=" * 80)
        print("SCAN SUMMARY")
        print("=" * 80)
        print(f"Stocks Processed        : {len(stock_df)}")
        print(f"Stocks Passing Filters  : {len(ranked)}")
        print(f"Price Filtered          : {price_filtered_count}")
        print(f"Liquidity Filtered      : {liquidity_filtered_count}")
        print(f"Insufficient Data       : {insufficient_data_count}")
        print(f"Download Failures       : {download_failed_count}")
        print(f"Indicator Failures      : {indicator_failed_count}")
    else:
        print("No stocks passed the price and liquidity filters.")
        print()
        print(f"Stocks Processed       : {len(stock_df)}")
        print(f"Price Filtered         : {price_filtered_count}")
        print(f"Liquidity Filtered     : {liquidity_filtered_count}")
        print(f"Insufficient Data      : {insufficient_data_count}")
        print(f"Download Failures      : {download_failed_count}")

    print("=" * 80)
    print("SCAN COMPLETED")
    print("=" * 80)
    return results


def scan_universe_parallel(stock_df, export_to_excel=True, max_workers=10):
    print("=" * 80)
    print("              AI STOCK SCANNER V3.2 - LIQUIDITY FILTERS")
    print("=" * 80)

    print(f"Loaded {len(stock_df)} stocks")
    print(f"Minimum Price                : ${MIN_PRICE:,.2f}")
    print(f"Parallel workers             : {max_workers}")
    print()

    results = []
    futures = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for _, row in stock_df.iterrows():
            futures.append(executor.submit(process_stock, row))

        for future in as_completed(futures):
            try:
                result = future.result()
                if result is not None:
                    results.append(result)
            except Exception as error:
                print(f"Parallel scan error: {error}")

    print("=" * 80)

    if results:
        print("Creating Excel Report...")
        ranked = rank_stocks(results)
        if export_to_excel:
            export_report(ranked.to_dict("records"))
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
            "Risk/Reward",
        ]

        available_columns = [column for column in display_columns if column in ranked.columns]
        print(ranked[available_columns].head(10).to_string(index=False))

        print()
        print("=" * 80)
        print("SCAN SUMMARY")
        print("=" * 80)
        print(f"Stocks Processed        : {len(stock_df)}")
        print(f"Stocks Passing Filters  : {len(ranked)}")
        print(f"Price Filtered          : 0")
        print(f"Liquidity Filtered      : 0")
        print(f"Insufficient Data       : 0")
        print(f"Download Failures       : 0")
        print(f"Indicator Failures      : 0")
    else:
        print("No stocks passed the price and liquidity filters.")
        print()
        print(f"Stocks Processed       : {len(stock_df)}")
        print(f"Price Filtered         : 0")
        print(f"Liquidity Filtered     : 0")
        print(f"Insufficient Data      : 0")
        print(f"Download Failures      : 0")

    print("=" * 80)
    print("SCAN COMPLETED")
    print("=" * 80)
    return results


def scan_watchlist(export_to_excel=True, parallel=False, max_workers=10):
    try:
        watchlist = load_watchlist()
    except Exception as error:
        print(f"Could not load watchlist: {error}")
        raise SystemExit(1)

    return scan_universe(
        watchlist,
        export_to_excel=export_to_excel,
        parallel=parallel,
        max_workers=max_workers,
    )


def scan_nyse(export_to_excel=True, limit=None, force_download=False, parallel=False, max_workers=10):
    try:
        tickers = load_nyse_tickers(
            force_download=force_download,
            limit=limit,
            use_yfinance=True,
        )
    except Exception as error:
        print(f"Could not load NYSE universe: {error}")
        raise SystemExit(1)

    if limit is not None:
        tickers = tickers.head(limit)

    tickers = tickers.rename(columns={"Exchange": "Market", "Security Name": "Sector"})

    print(f"Loaded NYSE universe: {len(tickers)} tickers (sorted by market cap)")

    return scan_universe(
        tickers,
        export_to_excel=export_to_excel,
        parallel=parallel,
        max_workers=max_workers,
    )


if __name__ == "__main__":
    scan_watchlist()
