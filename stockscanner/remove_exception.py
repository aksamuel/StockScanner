"""Remove a ticker from the stock exception CSV."""

import argparse
import csv
import os
import tempfile

from .config import EXCEPTION_LIST


def remove_exceptions(symbols, csv_path=EXCEPTION_LIST):
    """Atomically remove matching tickers and return the number of rows removed."""
    normalized_symbols = list(
        dict.fromkeys(symbol.strip().upper() for symbol in symbols if symbol.strip())
    )
    if not normalized_symbols:
        raise ValueError("At least one ticker symbol is required")

    with open(csv_path, newline="", encoding="utf-8-sig") as csv_file:
        reader = csv.DictReader(csv_file)
        columns = reader.fieldnames or []
        if "Symbol" not in columns:
            raise ValueError(f"Exception list has no Symbol column: {csv_path}")
        rows = list(reader)

    requested = set(normalized_symbols)
    available = {
        (row.get("Symbol") or "").strip().upper()
        for row in rows
        if (row.get("Symbol") or "").strip()
    }
    missing = requested - available
    if missing:
        raise ValueError(
            f"Ticker(s) not in the exception list: {', '.join(sorted(missing))}"
        )

    kept_rows = [
        row
        for row in rows
        if (row.get("Symbol") or "").strip().upper() not in requested
    ]
    removed_count = len(rows) - len(kept_rows)

    directory = os.path.dirname(os.path.abspath(csv_path))
    file_descriptor, temporary_path = tempfile.mkstemp(
        dir=directory, prefix="exceptions-", suffix=".csv"
    )
    try:
        with os.fdopen(file_descriptor, "w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=columns, lineterminator="\n")
            writer.writeheader()
            writer.writerows(kept_rows)
        os.replace(temporary_path, csv_path)
    except Exception:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)
        raise

    return removed_count


def remove_exception(symbol, csv_path=EXCEPTION_LIST):
    """Remove all rows matching one ticker and return the number removed."""
    try:
        return remove_exceptions([symbol], csv_path)
    except ValueError as error:
        if str(error).startswith("Ticker(s) not in the exception list:"):
            return 0
        raise


def main():
    parser = argparse.ArgumentParser(description="Remove tickers from exceptions.csv")
    parser.add_argument("symbols", help="Comma-separated ticker symbols to remove")
    parser.add_argument("--csv", default=EXCEPTION_LIST, help="Exception CSV path")
    args = parser.parse_args()

    symbols = args.symbols.split(",")
    try:
        removed_count = remove_exceptions(symbols, args.csv)
    except ValueError as error:
        parser.error(str(error))
    print(f"Removed {removed_count} exception row(s) from {args.csv}")


if __name__ == "__main__":
    main()
