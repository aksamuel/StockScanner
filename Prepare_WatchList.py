import pandas as pd

# DataHub NASDAQ listings (official mirror)
URL = "https://datahub.io/core/nasdaq-listings/r/nasdaq-listed-symbols.csv"

df = pd.read_csv(URL)

# Full NASDAQ ticker list (all symbols)
WATCHLIST = df["Symbol"].dropna().unique().tolist()

print(f"Total NASDAQ tickers loaded: {len(WATCHLIST)}")
print(WATCHLIST[:50])  # preview first 50 tickers
