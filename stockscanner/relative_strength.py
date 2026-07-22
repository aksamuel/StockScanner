import yfinance as yf


def calculate_relative_strength(symbol):
    try:
        stock = yf.Ticker(symbol).history(period="6mo")
        spy = yf.Ticker("SPY").history(period="6mo")

        if stock.empty or spy.empty:
            return 0.0

        stock_return = ((stock["Close"].iloc[-1] / stock["Close"].iloc[0]) - 1) * 100
        spy_return = ((spy["Close"].iloc[-1] / spy["Close"].iloc[0]) - 1) * 100

        return float(round(stock_return - spy_return, 2))

    except Exception as e:
        print(f"Relative Strength Error ({symbol}): {e}")
        return 0.0
