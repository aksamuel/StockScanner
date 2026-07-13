def score_stock(df, relative_strength):

    latest = df.iloc[-1]

    score = 0

    # -----------------------
    # Trend
    # -----------------------

    if latest["Close"] > latest["MA200"]:
        score += 20

    if latest["MA20"] > latest["MA50"]:
        score += 10

    if latest["MA50"] > latest["MA200"]:
        score += 15

    # -----------------------
    # RSI
    # -----------------------

    if 50 <= latest["RSI"] <= 70:
        score += 10

    # -----------------------
    # MACD
    # -----------------------

    if latest["MACD"] > latest["MACD_SIGNAL"]:
        score += 10

    # -----------------------
    # Volume
    # -----------------------

    if latest["Volume"] > latest["AVG_VOLUME"]:
        score += 10

    # -----------------------
    # 52 Week High
    # -----------------------

    high52 = df["High"].max()

    if latest["Close"] >= high52 * 0.85:
        score += 10

    # -----------------------
    # Momentum
    # -----------------------

    if latest["Close"] > df["Close"].iloc[-20]:
        score += 15

    # -----------------------
    # Relative Strength
    # -----------------------

    if relative_strength > 20:
        score += 10

    elif relative_strength > 10:
        score += 7

    elif relative_strength > 0:
        score += 3

    return min(score, 100)