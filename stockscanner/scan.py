import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from stockscanner.config import (
    MIN_PRICE,
    MIN_AVERAGE_DOLLAR_VOLUME,
    AVERAGE_VOLUME_DAYS,
    TOP_RESULTS,
)
from stockscanner.universe import load_nyse_tickers
from stockscanner.ticker_universe_store import load_latest_ticker_universe
from stockscanner.watchlist import load_watchlist
from stockscanner.market_data import (
    completed_daily_data,
    download_data,
    download_intraday_snapshot,
)
from stockscanner.indicators import calculate_indicators
from stockscanner.scoring import score_stock
from stockscanner.trade_plan import generate_trade_plan
from stockscanner.report import export_report, export_batch_reports
from stockscanner.html_report import export_html_report
from stockscanner.ranking import rank_stocks
from stockscanner.analyst_data import get_analyst_data
from stockscanner.signals import generate_signal
from stockscanner.relative_strength import calculate_relative_strength
from stockscanner.support_resistance import analyze_support_resistance


def _prefer_emoji(text_emoji: str, text_ascii: str) -> str:
    enc = sys.stdout.encoding or "utf-8"
    try:
        text_emoji.encode(enc)
        return text_emoji
    except Exception:
        return text_ascii


def get_recommendation(score):
    if score >= 90:
        return _prefer_emoji("🟢 STRONG BUY", "STRONG BUY")
    if score >= 80:
        return _prefer_emoji("🟢 BUY", "BUY")
    if score >= 70:
        return _prefer_emoji("🟡 ACCUMULATE", "ACCUMULATE")
    if score >= 60:
        return _prefer_emoji("🟡 HOLD", "HOLD")
    if score >= 40:
        return _prefer_emoji("🟠 WATCH", "WATCH")
    return _prefer_emoji("🔴 AVOID", "AVOID")


def process_stock(row, quiet=False, available_cash=1000, risk_percent=1):
    symbol = str(row.get("Symbol", "")).strip().upper()
    market = row.get("Market", "Unknown")
    sector = row.get("Sector", "Unknown")
    priority = row.get("Priority", "Normal")

    if not quiet:
        print("=" * 80)
        print(f"Scanning {symbol}")
        print("=" * 80)

    try:
        df = download_data(symbol)
    except Exception as error:
        print(f"Download Error: {error}")
        return None

    df = completed_daily_data(df)
    if df is None or df.empty or len(df) < 200:
        if not quiet:
            print("Not enough historical data.")
        return None

    try:
        df = calculate_indicators(df)
        latest = df.iloc[-1]
        average_volume = float(df["Volume"].tail(AVERAGE_VOLUME_DAYS).mean())
    except Exception as error:
        if not quiet:
            print(f"Indicator Error: {error}")
        return None

    analysis_df = df.copy()
    price_timestamp = str(analysis_df.index[-1])
    try:
        intraday = download_intraday_snapshot(symbol)
    except Exception as error:
        if not quiet:
            print(f"Intraday Data Error: {error}")
        intraday = None
    if intraday is not None:
        analysis_df.loc[analysis_df.index[-1], "Close"] = intraday["price"]
        analysis_df.loc[analysis_df.index[-1], "High"] = max(
            float(analysis_df["High"].iloc[-1]),
            intraday["price"],
        )
        analysis_df.loc[analysis_df.index[-1], "Volume"] = intraday["volume"]
        price_timestamp = intraday["timestamp"]

    latest = analysis_df.iloc[-1]
    current_price = float(latest["Close"])
    average_dollar_volume = current_price * average_volume
    try:
        zone_analysis = analyze_support_resistance(df, current_price=current_price)
    except Exception as error:
        if not quiet:
            print(f"Support/Resistance Error: {error}")
        zone_analysis = analyze_support_resistance(None)

    if current_price < MIN_PRICE:
        if not quiet:
            print("Skipped: price below minimum price.")
        return None

    if average_dollar_volume < MIN_AVERAGE_DOLLAR_VOLUME:
        if not quiet:
            print("Skipped: dollar volume below threshold.")
        return None

    if not quiet:
        print(f"Liquidity Check       : PASSED (${average_dollar_volume:,.0f})")

    try:
        relative_strength = float(calculate_relative_strength(symbol))
    except Exception as error:
        if not quiet:
            print(f"Relative Strength Error: {error}")
        relative_strength = 0.0

    try:
        score = score_stock(analysis_df, relative_strength)
        signal = generate_signal(analysis_df)
    except Exception as error:
        if not quiet:
            print(f"Score or Signal Error: {error}")
        return None

    recommendation = get_recommendation(score)

    try:
        plan = generate_trade_plan(
            analysis_df,
            available_cash=available_cash,
            risk_percent=risk_percent,
        )
    except Exception as error:
        if not quiet:
            print(f"Trade Plan Error: {error}")
        return None

    try:
        analyst_data = get_analyst_data(symbol, current_price)
    except Exception as error:
        if not quiet:
            print(f"Analyst Data Error: {error}")
        analyst_data = {
            "Analyst Rating": "Unavailable",
            "Target Upside": None,
        }

    market_cap = row.get("Market Cap", 0)
    try:
        market_cap = float(market_cap) if market_cap else 0
    except (ValueError, TypeError):
        market_cap = 0

    result = {
        "Symbol": symbol,
        "Market": market,
        "Sector": sector,
        "Analyst Rating": analyst_data["Analyst Rating"],
        "Target Upside": analyst_data["Target Upside"],
        "Suggested Shares": int(plan["Shares"]),
        "Risk/Reward": round(float(plan["RR"]), 2),
        "Priority": priority,
        "Market Cap": market_cap,
        "Current Price": round(current_price, 2),
        "Price As Of": price_timestamp,
        "Average Volume": round(average_volume, 0),
        "Average Dollar Volume": round(average_dollar_volume, 0),
        "Liquidity Status": "PASS",
        "20 MA": round(float(latest["MA20"]), 2),
        "50 MA": round(float(latest["MA50"]), 2),
        "200 MA": round(float(latest["MA200"]), 2),
        **zone_analysis,
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
        "Investment": round(float(plan["Investment"]), 2),
    }

    if not quiet:
        print(f"Recommendation       : {recommendation}")
        print()

    return result


def scan_universe(stock_df, export_to_excel=True, parallel=False, max_workers=10, batch_reports=False, quiet=False, progress=False, html_report=False, available_cash=1000, risk_percent=1):
    if parallel:
        return scan_universe_parallel(
            stock_df,
            export_to_excel=export_to_excel,
            max_workers=max_workers,
            batch_reports=batch_reports,
            quiet=quiet,
            progress=progress,
            html_report=html_report,
            available_cash=available_cash,
            risk_percent=risk_percent,
        )

    if not quiet:
        print("=" * 80)
        print("              AI STOCK SCANNER V3.2 - LIQUIDITY FILTERS")
        print("=" * 80)

        print(f"Loaded {len(stock_df)} stocks")
        print(f"Minimum Price                : ${MIN_PRICE:,.2f}")
        print()

    if progress and not quiet:
        print(f"Progress: 0/{len(stock_df)} (0%)")

    results = []
    download_failed_count = 0
    insufficient_data_count = 0
    indicator_failed_count = 0
    price_filtered_count = 0
    liquidity_filtered_count = 0

    total_stocks = len(stock_df)
    processed = 0
    for _, row in stock_df.iterrows():
        result = process_stock(row, quiet=quiet, available_cash=available_cash, risk_percent=risk_percent)
        processed += 1
        if progress:
            if total_stocks <= 20 or processed % max(1, total_stocks // 20) == 0 or processed == total_stocks:
                print(f"Progress: {processed}/{total_stocks} ({processed / total_stocks * 100:.0f}%)")
        if result is None:
            continue
        results.append(result)

    print("=" * 80)

    if results:
        if not quiet:
            print("Creating Excel Report...")
        ranked = rank_stocks(results)
        if export_to_excel:
            if batch_reports:
                export_batch_reports(ranked.to_dict("records"), top_count=10, batch_size=50)
            else:
                export_report(ranked.to_dict("records"))
        if html_report:
            export_html_report(ranked.to_dict("records"), quiet=quiet)
        if not quiet:
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
        if not quiet:
            print(ranked[available_columns].head(TOP_RESULTS).to_string(index=False))

        if not quiet:
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
        if not quiet:
            print("No stocks passed the price and liquidity filters.")
            print()
            print(f"Stocks Processed       : {len(stock_df)}")
            print(f"Price Filtered         : {price_filtered_count}")
            print(f"Liquidity Filtered     : {liquidity_filtered_count}")
            print(f"Insufficient Data      : {insufficient_data_count}")
            print(f"Download Failures      : {download_failed_count}")

    if not quiet:
        print("=" * 80)
        print("SCAN COMPLETED")
        print("=" * 80)
    return results


def scan_universe_parallel(stock_df, export_to_excel=True, max_workers=10, batch_reports=False, quiet=False, progress=False, html_report=False, available_cash=1000, risk_percent=1):
    if not quiet:
        print("=" * 80)
        print("              AI STOCK SCANNER V3.2 - LIQUIDITY FILTERS")
        print("=" * 80)

        print(f"Loaded {len(stock_df)} stocks")
        print(f"Minimum Price                : ${MIN_PRICE:,.2f}")
        print(f"Parallel workers             : {max_workers}")
        print()

    if progress and not quiet:
        print(f"Progress: 0/{len(stock_df)} (0%)")

    results = []
    futures = []
    completed = 0
    total_stocks = len(stock_df)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for _, row in stock_df.iterrows():
            futures.append(executor.submit(process_stock, row, quiet, available_cash, risk_percent))

        for future in as_completed(futures):
            completed += 1
            if progress and not quiet:
                if total_stocks <= 20 or completed % max(1, total_stocks // 20) == 0 or completed == total_stocks:
                    print(f"Progress: {completed}/{total_stocks} ({completed / total_stocks * 100:.0f}%)")
            try:
                result = future.result()
                if result is not None:
                    results.append(result)
            except Exception as error:
                if not quiet:
                    print(f"Parallel scan error: {error}")

    if not quiet:
        print("=" * 80)

    if results:
        if not quiet:
            print("Creating Excel Report...")
        ranked = rank_stocks(results)
        if export_to_excel:
            if batch_reports:
                export_batch_reports(ranked.to_dict("records"), top_count=10, batch_size=50)
            else:
                export_report(ranked.to_dict("records"))
        if html_report:
            export_html_report(ranked.to_dict("records"), quiet=quiet)
        if not quiet:
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
        if not quiet:
            print(ranked[available_columns].head(TOP_RESULTS).to_string(index=False))

        if not quiet:
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
        if not quiet:
            print("No stocks passed the price and liquidity filters.")
            print()
            print(f"Stocks Processed       : {len(stock_df)}")
            print(f"Price Filtered         : 0")
            print(f"Liquidity Filtered     : 0")
            print(f"Insufficient Data      : 0")
            print(f"Download Failures      : 0")

    if not quiet:
        print("=" * 80)
        print("SCAN COMPLETED")
        print("=" * 80)
    return results


def scan_watchlist(export_to_excel=True, parallel=False, max_workers=10, batch_reports=False, quiet=False, progress=False, html_report=False, available_cash=1000, risk_percent=1):
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
        batch_reports=batch_reports,
        quiet=quiet,
        progress=progress,
        html_report=html_report,
        available_cash=available_cash,
        risk_percent=risk_percent,
    )


def scan_nyse(export_to_excel=True, limit=None, force_download=False, universe_source="download", supabase_url="", supabase_secret_key="", parallel=False, max_workers=10, batch_reports=False, quiet=False, progress=False, html_report=False, available_cash=1000, risk_percent=1):
    try:
        if universe_source == "supabase":
            tickers = load_latest_ticker_universe(
                supabase_url=supabase_url,
                secret_key=supabase_secret_key,
                limit=limit,
            )
        else:
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

    if not quiet:
        print(f"Loaded NYSE universe: {len(tickers)} tickers (sorted by market cap)")

    return scan_universe(
        tickers,
        export_to_excel=export_to_excel,
        parallel=parallel,
        max_workers=max_workers,
        batch_reports=batch_reports,
        quiet=quiet,
        progress=progress,
        html_report=html_report,
        available_cash=available_cash,
        risk_percent=risk_percent,
    )


if __name__ == "__main__":
    scan_watchlist()
