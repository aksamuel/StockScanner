import pandas as pd

from stockscanner.watchlist import load_exceptions


def setup_priority(signal):
    """Return the secondary ranking priority for a scan setup."""
    normalized_signal = str(signal).casefold()
    if "strong uptrend" in normalized_signal:
        return 4
    if "pullback to 20" in normalized_signal:
        return 3
    if "pullback to 50" in normalized_signal:
        return 2
    if "breakout candidate" in normalized_signal:
        return 1
    return 0


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

    sort_columns = []
    for column in ["Score", "Risk/Reward", "Relative Strength"]:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0)

    if "Score" in df.columns:
        sort_columns.append("Score")
    if "Signal" in df.columns:
        df["_setup_priority"] = df["Signal"].map(setup_priority)
        sort_columns.append("_setup_priority")
    sort_columns.extend(
        column
        for column in ["Risk/Reward", "Relative Strength"]
        if column in df.columns
    )
    if sort_columns:
        df.sort_values(by=sort_columns, ascending=False, inplace=True)

    df.drop(columns=["_setup_priority"], errors="ignore", inplace=True)
    df.reset_index(drop=True, inplace=True)
    df.insert(0, "Rank", df.index + 1)

    return df
