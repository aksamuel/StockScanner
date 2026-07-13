def generate_trade_plan(df, available_cash=10000, risk_percent=1):

    latest = df.iloc[-1]

    price = latest["Close"]
    ma20 = latest["MA20"]
    ma50 = latest["MA50"]
    ma200 = latest["MA200"]

    high20 = df["High"].tail(20).max()

    # -----------------------------
    # Determine Entry Price
    # -----------------------------
    if price > ma20 > ma50 > ma200:
        trend = "Strong Uptrend"
        entry = ma20
        stop = ma50

    elif price > ma50 > ma200:
        trend = "Healthy Pullback"
        entry = ma50
        stop = ma200

    else:
        trend = "Breakout"
        entry = high20 * 1.01
        stop = ma20

    # -----------------------------
    # Profit Targets
    # -----------------------------
    target1 = entry * 1.06
    target2 = entry * 1.10
    target3 = entry * 1.15

    # -----------------------------
    # Risk / Reward
    # -----------------------------
    risk = entry - stop
    reward = target2 - entry

    if risk <= 0:
        rr = 0
    else:
        rr = reward / risk

    # -----------------------------
    # Position Size
    # -----------------------------
    risk_amount = available_cash * (risk_percent / 100)

    if risk > 0:
        shares = int(risk_amount / risk)
    else:
        shares = 0

    investment = shares * entry

    return {
        "Trend": trend,
        "Entry": entry,
        "Stop": stop,
        "Target1": target1,
        "Target2": target2,
        "Target3": target3,
        "RR": rr,
        "Shares": shares,
        "Investment": investment
    }