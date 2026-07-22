import argparse
from pathlib import Path

from stockscanner.universe import (
    NYSE_CSV,
    download_nyse_tickers,
    download_nyse_tickers_yfinance,
    load_nyse_tickers,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Download the NYSE ticker universe file for StockScanner."
    )
    parser.add_argument(
        "--force-download",
        action="store_true",
        help="Force download the NYSE ticker file from the NASDAQ source."
    )
    parser.add_argument(
        "--force-yfinance",
        action="store_true",
        help="Force download the NYSE ticker list using yfinance instead of the NASDAQ source."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit the number of tickers saved for a quick test run."
    )
    return parser.parse_args()


def main():
    args = parse_args()
    Path(NYSE_CSV).parent.mkdir(parents=True, exist_ok=True)

    if args.force_yfinance:
        print("Downloading NYSE tickers using yfinance...")
        df = download_nyse_tickers_yfinance(path=NYSE_CSV, limit=args.limit)
    elif args.force_download:
        print("Downloading NYSE tickers from the NASDAQ source...")
        try:
            df = download_nyse_tickers(path=NYSE_CSV)
        except Exception as error:
            print(f"NASDAQ download failed: {error}")
            print("Falling back to yfinance...")
            df = download_nyse_tickers_yfinance(path=NYSE_CSV, limit=args.limit)
    else:
        print("Loading existing ticker file or downloading if missing...")
        df = load_nyse_tickers(path=NYSE_CSV, limit=args.limit, use_yfinance=False)

    print(f"Saved {len(df)} NYSE tickers to {NYSE_CSV}")


if __name__ == "__main__":
    main()
