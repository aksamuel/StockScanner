"""Remove a ticker from the stock exception CSV."""

import argparse
import csv
import os
import tempfile

from .config import EXCEPTION_LIST


def remove_exception(symbol, csv_path=EXCEPTION_LIST):
    """Remove all rows matching a ticker and return the number removed."""
    normalized_symbol = symbol.strip().upper()
    if not normalized_symbol:
        raise ValueError("Ticker symbol is required")

    with open(csv_path, newline="", encoding="utf-8-sig") as csv_file:
        reader = csv.DictReader(csv_file)
        columns = reader.fieldnames or []
        if "Symbol" not in columns:
            raise ValueError(f"Exception list has no Symbol column: {csv_path}")
        rows = list(reader)

    kept_rows = [
        row
        for row in rows
        if (row.get("Symbol") or "").strip().upper() != normalized_symbol
    ]
    removed_count = len(rows) - len(kept_rows)
    if removed_count == 0:
        return 0

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


def main():
    parser = argparse.ArgumentParser(description="Remove a ticker from exceptions.csv")
    parser.add_argument("symbol", help="Ticker symbol to remove")
    parser.add_argument("--csv", default=EXCEPTION_LIST, help="Exception CSV path")
    args = parser.parse_args()

    removed_count = remove_exception(args.symbol, args.csv)
    if removed_count == 0:
        parser.error(f"Ticker is not in the exception list: {args.symbol}")
    print(f"Removed {args.symbol.strip().upper()} from {args.csv}")


if __name__ == "__main__":
    main()
