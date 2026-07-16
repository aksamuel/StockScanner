from pathlib import Path

import pandas as pd

from config import WATCHLIST_FILE


def load_watchlist() -> pd.DataFrame:
    """Load the configured scanner universe."""

    filepath = Path(WATCHLIST_FILE)

    if not filepath.exists():
        raise FileNotFoundError(
            f"Watchlist file not found: {filepath.resolve()}"
        )

    dataframe = pd.read_csv(filepath)

    required_columns = [
        "Symbol",
        "Market",
        "Sector",
        "Priority",
        "Enabled",
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in dataframe.columns
    ]

    if missing_columns:
        raise ValueError(
            f"Watchlist is missing columns: {missing_columns}"
        )

    dataframe["Symbol"] = (
        dataframe["Symbol"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    dataframe["Enabled"] = (
        dataframe["Enabled"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    dataframe = dataframe[
        dataframe["Enabled"].isin(
            ["YES", "Y", "TRUE", "1"]
        )
    ].copy()

    dataframe = (
        dataframe
        .drop_duplicates(subset=["Symbol"])
        .reset_index(drop=True)
    )

    return dataframe