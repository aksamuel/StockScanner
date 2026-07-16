from io import StringIO
from pathlib import Path

import pandas as pd
import requests


SYMBOL_DIRECTORY_URL = (
    "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"
)

OUTPUT_FILE = Path("watchlists/nyse_stocks.csv")


def convert_to_yahoo_symbol(symbol: str) -> str:
    """
    Convert exchange-style symbols to Yahoo Finance format.

    Examples:
        BRK.B -> BRK-B
        BF.B  -> BF-B
    """

    return symbol.strip().replace(".", "-")


def is_regular_equity(row: pd.Series) -> bool:
    """
    Exclude ETFs, test issues, preferred shares, warrants,
    rights, units, notes and other non-common-equity securities.
    """

    symbol = str(row["ACT Symbol"]).strip()
    security_name = str(row["Security Name"]).upper()

    if not symbol:
        return False

    # NYSE only
    if row["Exchange"] != "N":
        return False

    # Exclude ETFs and test securities
    if row["ETF"] != "N":
        return False

    if row["Test Issue"] != "N":
        return False

    # Exclude common special-security symbol patterns
    excluded_symbol_parts = [
        "$",       # Preferred shares
        ".W",      # Warrants
        ".U",      # Units
        ".R",      # Rights
        "^",
    ]

    if any(part in symbol for part in excluded_symbol_parts):
        return False

    excluded_name_terms = [
        "PREFERRED",
        "WARRANT",
        "RIGHTS",
        "RIGHT ",
        "UNIT",
        "NOTES DUE",
        "NOTE DUE",
        "DEBENTURE",
        "BOND",
        "EXCHANGE TRADED",
        "ETF",
        "ETN",
        "FUND",
        "ACQUISITION CORP",
        "ACQUISITION COMPANY",
    ]

    if any(term in security_name for term in excluded_name_terms):
        return False

    return True


def download_nyse_universe() -> pd.DataFrame:
    """Download and clean the NYSE stock universe."""

    response = requests.get(
        SYMBOL_DIRECTORY_URL,
        timeout=30
    )
    response.raise_for_status()

    raw_text = response.text

    dataframe = pd.read_csv(
        StringIO(raw_text),
        sep="|"
    )

    # Remove the final file-creation-time row
    dataframe = dataframe[
        ~dataframe["ACT Symbol"]
        .astype(str)
        .str.startswith("File Creation Time")
    ].copy()

    required_columns = [
        "ACT Symbol",
        "Security Name",
        "Exchange",
        "ETF",
        "Test Issue",
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in dataframe.columns
    ]

    if missing_columns:
        raise ValueError(
            f"Missing expected columns: {missing_columns}"
        )

    nyse = dataframe[
        dataframe.apply(
            is_regular_equity,
            axis=1
        )
    ].copy()

    nyse["Symbol"] = (
        nyse["ACT Symbol"]
        .astype(str)
        .map(convert_to_yahoo_symbol)
    )

    nyse["Company"] = (
        nyse["Security Name"]
        .astype(str)
        .str.strip()
    )

    nyse["Market"] = "NYSE"
    nyse["Sector"] = "Unknown"
    nyse["Priority"] = "Normal"
    nyse["Enabled"] = "Yes"

    nyse = nyse[
        [
            "Symbol",
            "Company",
            "Market",
            "Sector",
            "Priority",
            "Enabled",
        ]
    ]

    nyse = (
        nyse
        .dropna(subset=["Symbol"])
        .drop_duplicates(subset=["Symbol"])
        .sort_values("Symbol")
        .reset_index(drop=True)
    )

    return nyse


def main():
    """Create the NYSE watchlist CSV."""

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    nyse = download_nyse_universe()

    nyse.to_csv(
        OUTPUT_FILE,
        index=False
    )

    print("=" * 70)
    print("NYSE universe created successfully")
    print(f"Stocks included : {len(nyse):,}")
    print(f"Output file     : {OUTPUT_FILE.resolve()}")
    print("=" * 70)

    print()
    print(nyse.head(20).to_string(index=False))


if __name__ == "__main__":
    main()