"""Add time-bounded tickers to the stock exception CSV."""

import argparse
import csv
import os
import tempfile
from datetime import date, timedelta

from .config import EXCEPTION_LIST
from .exception_list import sort_exception_rows


def add_exceptions(
    symbols,
    csv_path=EXCEPTION_LIST,
    date_from=None,
    reason="Added from scanner dashboard",
):
    """Atomically append 30-day exception rows and return the number added."""
    normalized_symbols = list(
        dict.fromkeys(symbol.strip().upper() for symbol in symbols if symbol.strip())
    )
    if not normalized_symbols:
        raise ValueError("At least one ticker symbol is required")
    reason = str(reason or "").strip()
    if not reason:
        raise ValueError("An exception reason is required")
    if len(reason) > 200 or "\n" in reason or "\r" in reason:
        raise ValueError("Exception reason must be a single line of 200 characters or fewer")

    with open(csv_path, newline="", encoding="utf-8-sig") as csv_file:
        reader = csv.DictReader(csv_file)
        columns = reader.fieldnames or []
        required_columns = {"Symbol", "Date From", "Date To", "Reason"}
        if not required_columns.issubset(columns):
            missing = ", ".join(sorted(required_columns - set(columns)))
            raise ValueError(f"Exception list is missing column(s): {missing}")
        rows = list(reader)

    existing_symbols = {
        (row.get("Symbol") or "").strip().upper()
        for row in rows
        if (row.get("Symbol") or "").strip()
    }
    duplicates = set(normalized_symbols) & existing_symbols
    if duplicates:
        raise ValueError(
            f"Ticker(s) already in the exception list: {', '.join(sorted(duplicates))}"
        )

    start_date = date_from or date.today()
    end_date = start_date + timedelta(days=30)
    formatted_start = start_date.strftime("%d/%b/%Y")
    formatted_end = end_date.strftime("%d/%b/%Y")

    for symbol in normalized_symbols:
        rows.append(
            {
                "Symbol": symbol,
                "Date From": formatted_start,
                "Date To": formatted_end,
                "Reason": reason,
            }
        )
    rows = sort_exception_rows(rows)

    directory = os.path.dirname(os.path.abspath(csv_path))
    file_descriptor, temporary_path = tempfile.mkstemp(
        dir=directory, prefix="exceptions-", suffix=".csv"
    )
    try:
        with os.fdopen(file_descriptor, "w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=columns, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary_path, csv_path)
    except Exception:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)
        raise

    return len(normalized_symbols)


def main():
    parser = argparse.ArgumentParser(description="Add tickers to exceptions.csv")
    parser.add_argument("symbols", help="Comma-separated ticker symbols to add")
    parser.add_argument("--csv", default=EXCEPTION_LIST, help="Exception CSV path")
    parser.add_argument(
        "--reason",
        default="Added from scanner dashboard",
        help="Reason stored for each exception",
    )
    args = parser.parse_args()

    try:
        added_count = add_exceptions(
            args.symbols.split(","),
            args.csv,
            reason=args.reason,
        )
    except ValueError as error:
        parser.error(str(error))
    print(f"Added {added_count} 30-day exception(s) to {args.csv}")


if __name__ == "__main__":
    main()
