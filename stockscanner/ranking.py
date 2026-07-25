import pandas as pd

from stockscanner.watchlist import load_exceptions


def rank_stocks(results):
    df = pd.DataFrame(results)

    if df.empty:
        return df

    # Filter out exception-listed stocks
    exceptions = load_exceptions()
    if exceptions and "Symbol" in df.columns:
        mask = df["Symbol"].str.upper().isin(exceptions)
        excluded_count = mask.sum()
        if excluded_count > 0:
            print(f"Excluded {excluded_count} stock(s) from exception list: "
                  f"{', '.join(sorted(df.loc[mask, 'Symbol'].tolist()))}")
            df = df[~mask]

    df["Market Cap"] = pd.to_numeric(df.get("Market Cap", 0), errors="coerce").fillna(0)

    df["is_strong_uptrend"] = df["Signal"].astype(str).str.contains("Strong Uptrend", case=False, na=False)
    df["is_pullback_20"] = df["Signal"].astype(str).str.contains("Pullback to 20", case=False, na=False)

    rsi = pd.to_numeric(df.get("RSI", 0), errors="coerce").fillna(0)
    df["rsi_score"] = rsi.apply(lambda x: 70 - abs(x - 60) if 50 <= x <= 70 else 0)

    df.sort_values(
        by=["Market Cap", "rsi_score", "is_strong_uptrend", "is_pullback_20"],
        ascending=[False, False, False, False],
        inplace=True,
    )

    df.drop(columns=["is_strong_uptrend", "is_pullback_20", "rsi_score"], inplace=True)
    df.reset_index(drop=True, inplace=True)
    df.insert(0, "Rank", df.index + 1)

    return df
