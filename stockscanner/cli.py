import argparse

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
    return parser.parse_args()


def main():
    args = parse_args()
    if args.universe:
        scan_nyse(
            export_to_excel=not args.no_report,
            limit=args.limit,
            force_download=args.force_download,
            parallel=args.parallel,
            max_workers=args.workers,
        )
    else:
        scan_watchlist(
            export_to_excel=not args.no_report,
            parallel=args.parallel,
            max_workers=args.workers,
        )


if __name__ == "__main__":
    main()
