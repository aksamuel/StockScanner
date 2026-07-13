import pandas as pd


def rank_stocks(results):

    df = pd.DataFrame(results)

    if df.empty:
        return df

    # Highest score first
    df.sort_values(
        by=[
            "Score",
            "Risk/Reward",
            "Relative Strength"
        ],
        ascending=[False, False, False]
    )

    # Reset index
    df.reset_index(drop=True, inplace=True)

    # Add ranking
    df.insert(0, "Rank", df.index + 1)

    return df