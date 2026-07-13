def generate_signal(df):

    latest = df.iloc[-1]

    close = latest["Close"]
    ma20 = latest["MA20"]
    ma50 = latest["MA50"]
    ma200 = latest["MA200"]
    rsi = latest["RSI"]
    macd = latest["MACD"]
    macd_signal = latest["MACD_SIGNAL"]

    # ---------------------------------------------------
    # Strong Uptrend
    # ---------------------------------------------------
    if (
        close > ma20 > ma50 > ma200
        and macd > macd_signal
        and 50 <= rsi <= 70
    ):
        return "🟢 Strong Uptrend"

    # ---------------------------------------------------
    # Pullback to 20 MA
    # ---------------------------------------------------
    if (
        close >= ma20 * 0.98
        and close <= ma20 * 1.02
        and ma20 > ma50 > ma200
    ):
        return "🟢 Pullback to 20 MA"

    # ---------------------------------------------------
    # Pullback to 50 MA
    # ---------------------------------------------------
    if (
        close >= ma50 * 0.98
        and close <= ma50 * 1.02
        and ma50 > ma200
    ):
        return "🟢 Pullback to 50 MA"

    # ---------------------------------------------------
    # Breakout Candidate
    # ---------------------------------------------------
    high20 = df["High"].tail(20).max()

    if (
        close >= high20 * 0.99
        and macd > macd_signal
    ):
        return "🔵 Breakout Candidate"

    # ---------------------------------------------------
    # Oversold Recovery
    # ---------------------------------------------------
    if (
        rsi < 35
        and macd > macd_signal
    ):
        return "🟠 Oversold Recovery"

    # ---------------------------------------------------
    # Strong Momentum
    # ---------------------------------------------------
    if (
        rsi > 65
        and macd > macd_signal
    ):
        return "🟡 Strong Momentum"

    return "⚪ Neutral"