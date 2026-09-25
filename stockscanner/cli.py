import argparse

from stockscanner.market_data import download_data
from stockscanner.supabase_store import SupabaseSnapshotStore
from stockscanner.universe import load_nyse_tickers

from .scan import scan_nyse, scan_watchlist


def parse_args():
    parser = argparse.ArgumentParser(description="Run the StockScanner workflow.")
    parser.add_argument("--no-report", action="store_true", help="Skip Excel report export.")
    parser.add_argument("--universe", action="store_true", help="Scan the full NYSE universe instead of the watchlist.")
    parser.add_argument("--limit", type=int, default=None, help="Limit the number of NYSE tickers processed for a faster test run.")
    parser.add_argument("--force-download", action="store_true", help="Force download of the latest NYSE ticker universe file.")
    parser.add_argument("--parallel", action="store_true", help="Run stock scans in parallel across multiple threads.")
    parser.add_argument("--workers", type=int, default=10, help="Number of parallel worker threads to use when --parallel is enabled.")
    parser.add_argument("--batch-reports", action="store_true", help="Produce top-10 and batch Excel reports and a combined report.")
    parser.add_argument("--progress", action="store_true", help="Show progress updates during long scans.")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-ticker console output for faster scans.")
    parser.add_argument("--daily-seed", action="store_true", help="Seed the NYSE universe for today into Supabase tables.")
    parser.add_argument("--hourly-collection", action="store_true", help="Retry the current hour's missing ticker snapshot collection.")
    parser.add_argument("--batch-size", type=int, default=25, help="Number of tickers to claim and process per hourly collection pass.")
    parser.add_argument("--slot-key", default=None, help="Override the hourly slot key (format YYYY-MM-DDTHH:00).")
    return parser.parse_args()


def _download_ticker_price(symbol):
    df = download_data(symbol)
    if df is None or df.empty:
        return None
    close = df.iloc[-1].get("Close")
    if close is None:
        return None
    return {"symbol": str(symbol).upper(), "price": float(close)}


def _seed_daily_universe():
    try:
        df = load_nyse_tickers(force_download=False)
        tickers = [str(symbol).strip().upper() for symbol in df["Symbol"].tolist() if str(symbol).strip()]
        store = SupabaseSnapshotStore()
        result = store.seed_daily_universe(tickers)
        print(f"Daily seed complete: {len(result)} tickers prepared.")
        return {"status": "seeded", "count": len(result)}
    except ValueError as exc:
        print(f"Supabase not configured: {exc}")
        return {"status": "skipped", "reason": "supabase_not_configured"}


def _hourly_collection(slot_key=None, batch_size=25):
    try:
        store = SupabaseSnapshotStore()
        result = store.collect_hourly_snapshot(
            slot_key=slot_key,
            batch_size=batch_size,
            downloader=_download_ticker_price,
        )
        print(f"Hourly collection: {result['status']} ({result['collected']} collected, {result['remaining']} remaining)")
        return result
    except ValueError as exc:
        print(f"Supabase not configured: {exc}")
        return {"status": "no_snapshot", "collected": 0, "remaining": 0, "snapshot": False, "reason": "supabase_not_configured"}


def main():
    args = parse_args()
    if args.daily_seed:
        _seed_daily_universe()
        return
    if args.hourly_collection:
        _hourly_collection(slot_key=args.slot_key, batch_size=args.batch_size)
        return
    if args.universe:
        scan_nyse(
            export_to_excel=not args.no_report,
            limit=args.limit,
            force_download=args.force_download,
            parallel=args.parallel,
            max_workers=args.workers,
            batch_reports=args.batch_reports,
            quiet=args.quiet,
            progress=args.progress,
        )
    else:
        scan_watchlist(
            export_to_excel=not args.no_report,
            parallel=args.parallel,
            max_workers=args.workers,
            batch_reports=args.batch_reports,
            quiet=args.quiet,
            progress=args.progress,
        )


if __name__ == "__main__":
    main()
