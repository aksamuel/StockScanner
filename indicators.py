import ta

def calculate_indicators(df):

    # Moving Averages
    df["MA20"] = df["Close"].rolling(20).mean()
    df["MA50"] = df["Close"].rolling(50).mean()
    df["MA200"] = df["Close"].rolling(200).mean()

    # RSI
    df["RSI"] = ta.momentum.RSIIndicator(
        close=df["Close"],
        window=14
    ).rsi()

    # MACD
    macd = ta.trend.MACD(df["Close"])

    df["MACD"] = macd.macd()
    df["MACD_SIGNAL"] = macd.macd_signal()

    # Average Volume
    df["AVG_VOLUME"] = df["Volume"].rolling(20).mean()

    return df