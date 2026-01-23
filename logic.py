def find_signal(option_chain, spot):

    strikes = option_chain["data"]
    
    # Find ATM strike
    atm = min(strikes, key=lambda x: abs(x["strikePrice"] - spot))
    idx = strikes.index(atm)

    # ATM ± 1 strikes
    candidates = strikes[idx-1:idx+2]

    best_call = None
    best_put = None

    for s in candidates:
        ce = s["call"]
        pe = s["put"]

        # Bullish logic
        if (
            0.4 <= ce["delta"] <= 0.65 and
            ce["oiChange"] > 0 and
            pe["oiChange"] < 0
        ):
            best_call = s["strikePrice"]

        # Bearish logic
        if (
            -0.65 <= pe["delta"] <= -0.4 and
            pe["oiChange"] > 0 and
            ce["oiChange"] < 0
        ):
            best_put = s["strikePrice"]

    if best_call:
        return "BUY CALL", best_call

    if best_put:
        return "BUY PUT", best_put

    return "NO TRADE", None
