import argparse
import json
import os
from pathlib import Path

from .scan import scan_nyse, scan_watchlist


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run the StockScanner workflow."
    )
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="Skip Excel report export."
    )
    parser.add_argument(
        "--universe",
        action="store_true",
        help="Scan the full NYSE universe instead of the watchlist."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit the number of NYSE tickers processed for a faster test run."
    )
    parser.add_argument(
        "--force-download",
        action="store_true",
        help="Force download of the latest NYSE ticker universe file."
    )
    parser.add_argument(
        "--universe-source",
        choices=("download", "supabase"),
        default="download",
        help="Load the NYSE universe from a live download or Supabase.",
    )
    parser.add_argument(
        "--include-portfolio-symbols",
        action="store_true",
        help="Also analyse held symbols without adding them to scanner rankings.",
    )
    parser.add_argument(
        "--parallel",
        action="store_true",
        help="Run stock scans in parallel across multiple threads."
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=10,
        help="Number of parallel worker threads to use when --parallel is enabled."
    )
    parser.add_argument(
        "--batch-reports",
        action="store_true",
        help="Produce top-10 and batch Excel reports (top 10 + batches of 50) and combined report.",
    )
    parser.add_argument(
        "--progress",
        action="store_true",
        help="Show progress updates during long scans."
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-ticker console output for faster scans.",
    )
    parser.add_argument(
        "--html",
        action="store_true",
        help="Generate an interactive HTML dashboard alongside the Excel report.",
    )
    parser.add_argument(
        "--failed-symbols-output",
        help="Write symbols without usable daily history to a JSON file.",
    )
    parser.add_argument(
        "--retry-symbols-file",
        help="Add prior failed symbols from a pending-retry JSON file to a universe scan.",
    )
    parser.add_argument(
        "--portfolio",
        type=float,
        default=50000,
        help="Total portfolio value in dollars (default: 50000).",
    )
    parser.add_argument(
        "--position-size",
        type=float,
        default=5,
        help="Max percentage of portfolio per position (default: 5%%).",
    )
    parser.add_argument(
        "--risk",
        type=float,
        default=1,
        help="Risk percentage per trade (default: 1%%).",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    available_cash = args.portfolio * (args.position_size / 100)
    retry_symbols = []
    if args.retry_symbols_file:
        payload = json.loads(Path(args.retry_symbols_file).read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("symbols"), list):
            raise ValueError("Retry-symbol input must contain a symbols array")
        retry_symbols = [
            str(item.get("symbol", "")).strip().upper()
            for item in payload["symbols"]
            if isinstance(item, dict) and str(item.get("symbol", "")).strip()
        ]
    if args.universe:
        scan_nyse(
            export_to_excel=not args.no_report,
            limit=args.limit,
            force_download=args.force_download,
            universe_source=args.universe_source,
            supabase_url=os.environ.get("SUPABASE_URL", ""),
            supabase_secret_key=os.environ.get("SUPABASE_SECRET_KEY", ""),
            include_portfolio_symbols=args.include_portfolio_symbols,
            parallel=args.parallel,
            max_workers=args.workers,
            batch_reports=args.batch_reports,
            quiet=args.quiet,
            progress=args.progress,
            html_report=args.html,
            available_cash=available_cash,
            risk_percent=args.risk,
            failed_symbols_output=args.failed_symbols_output,
            retry_symbols=retry_symbols,
        )
    else:
        scan_watchlist(
            export_to_excel=not args.no_report,
            parallel=args.parallel,
            max_workers=args.workers,
            batch_reports=args.batch_reports,
            quiet=args.quiet,
            progress=args.progress,
            html_report=args.html,
            available_cash=available_cash,
            risk_percent=args.risk,
        )


if __name__ == "__main__":
    main()
