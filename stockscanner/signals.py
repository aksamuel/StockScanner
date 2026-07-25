import sys


def _prefer_emoji(text_emoji: str, text_ascii: str) -> str:
    enc = sys.stdout.encoding or "utf-8"
    try:
        text_emoji.encode(enc)
        return text_emoji
    except Exception:
        return text_ascii


def generate_signal(df):
    latest = df.iloc[-1]

    close = latest["Close"]
    ma20 = latest["MA20"]
    ma50 = latest["MA50"]
    ma200 = latest["MA200"]
    rsi = latest["RSI"]
    macd = latest["MACD"]
    macd_signal = latest["MACD_SIGNAL"]

    if (
        close > ma20 > ma50 > ma200
        and macd > macd_signal
        and 50 <= rsi <= 70
    ):
        return _prefer_emoji("🟢 Strong Uptrend", "Strong Uptrend")

    if (
        close >= ma20 * 0.98
        and close <= ma20 * 1.02
        and ma20 > ma50 > ma200
    ):
        return _prefer_emoji("🟢 Pullback to 20 MA", "Pullback to 20 MA")

    if (
        close >= ma50 * 0.98
        and close <= ma50 * 1.02
        and ma50 > ma200
    ):
        return _prefer_emoji("🟢 Pullback to 50 MA", "Pullback to 50 MA")

    high20 = df["High"].tail(20).max()

    if (
        close >= high20 * 0.99
        and macd > macd_signal
    ):
        return _prefer_emoji("🔵 Breakout Candidate", "Breakout Candidate")

    if (
        rsi < 35
        and macd > macd_signal
    ):
        return _prefer_emoji("🟠 Oversold Recovery", "Oversold Recovery")

    if (
        rsi > 65
        and macd > macd_signal
    ):
        return _prefer_emoji("🟡 Strong Momentum", "Strong Momentum")

    return _prefer_emoji("⚪ Neutral", "Neutral")
