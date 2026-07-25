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

    # Highest score first
    df.sort_values(
        by=[
            "Score",
            "Risk/Reward",
            "Relative Strength"
        ],
        ascending=[False, False, False],
        inplace=True
    )

    df.reset_index(drop=True, inplace=True)
    df.insert(0, "Rank", df.index + 1)

    return df
