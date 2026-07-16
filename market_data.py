import pandas as pd
import yfinance as yf


def download_data(symbol):
    """Download one year of daily historical market data."""

    symbol = str(symbol).strip().upper()

    if not symbol:
        return pd.DataFrame()

    stock = yf.Ticker(symbol)

    df = stock.history(
        period="1y",
        interval="1d",
        auto_adjust=True
    )

    if df is None or df.empty:
        return pd.DataFrame()

    required_columns = [
        "Open",
        "High",
        "Low",
        "Close",
        "Volume"
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in df.columns
    ]

    if missing_columns:
        raise ValueError(
            f"{symbol} is missing columns: {missing_columns}"
        )

    df = df[
        ~df.index.duplicated(keep="last")
    ].copy()

    df = df.sort_index()

    df = df.dropna(
        subset=["Close", "Volume"]
    )

    return df