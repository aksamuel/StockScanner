from pathlib import Path

import pandas as pd
import yfinance as yf

BASE_DIR = Path(__file__).resolve().parent.parent
NYSE_URL = "https://ftp.nasdaqtrader.com/SymbolDirectory/nyse-listed.txt"
NYSE_CSV = BASE_DIR / "data" / "nyse_tickers.csv"


def download_nyse_tickers(path: Path = NYSE_CSV) -> pd.DataFrame:
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(NYSE_URL, sep="|", dtype=str)
    df = df[df["ETF"] == "N"]
    df = df[df["Test Issue"] == "N"]
    df = df[df["ACT Symbol"].str.strip() != ""]
    df = df[["ACT Symbol", "Security Name", "Exchange"]]
    df.columns = ["Symbol", "Security Name", "Exchange"]
    df["Symbol"] = df["Symbol"].str.strip().str.upper()
    df.to_csv(path, index=False)
    return df


def download_nyse_tickers_yfinance(path: Path = NYSE_CSV, limit: int | None = None) -> pd.DataFrame:
    path.parent.mkdir(parents=True, exist_ok=True)

    query = yf.screener.query.EquityQuery("is-in", ["exchange", "NYQ"])
    rows = []
    offset = 0
    page_size = 100

    while True:
        result = yf.screener.screen(query, size=page_size, count=page_size, offset=offset)
        quotes = result.get("quotes", [])
        if not quotes:
            break

        for quote in quotes:
            rows.append(
                {
                    "Symbol": str(quote.get("symbol", "")).strip().upper(),
                    "Security Name": quote.get("longName") or quote.get("shortName") or "",
                    "Exchange": quote.get("exchange", "NYQ"),
                    "Market Cap": int(quote.get("marketCap") or 0),
                }
            )

        offset += len(quotes)
        if offset >= result.get("total", offset):
            break

    if not rows:
        raise RuntimeError("yfinance NYSE ticker download returned no symbols.")

    df = pd.DataFrame(rows)
    df = df[df["Symbol"] != ""].drop_duplicates(subset=["Symbol"])
    df["Market Cap"] = pd.to_numeric(df["Market Cap"], errors="coerce").fillna(0).astype("int64")
    df = df.sort_values(by="Market Cap", ascending=False).reset_index(drop=True)

    if limit is not None:
        df = df.head(limit)

    df.to_csv(path, index=False)
    return df


def load_nyse_tickers(path: Path = NYSE_CSV, force_download: bool = False, limit: int | None = None, use_yfinance: bool = False) -> pd.DataFrame:
    if force_download or use_yfinance or not path.exists():
        if use_yfinance:
            try:
                return download_nyse_tickers_yfinance(path, limit=limit)
            except Exception:
                pass

        try:
            return download_nyse_tickers(path)
        except Exception:
            try:
                return download_nyse_tickers_yfinance(path, limit=limit)
            except Exception as error:
                if path.exists():
                    return pd.read_csv(path, dtype=str)
                raise

    df = pd.read_csv(path, dtype=str)
    if limit is not None:
        return df.head(limit)
    return df
