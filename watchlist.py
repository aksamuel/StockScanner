import pandas as pd


def load_watchlist():

    df = pd.read_csv("watchlists/watchlist.csv")

    # Keep only enabled stocks
    df = df[df["Enabled"] == "Yes"]

    return df