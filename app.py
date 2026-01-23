import streamlit as st
import time
from dhan_api import get_option_chain
from logic import find_signal

st.set_page_config(page_title="NIFTY Option Scanner", layout="wide")

st.title("📊 NIFTY Weekly Option Scanner")

access_token = st.text_input("Enter Dhan Access Token", type="password")
expiry = st.text_input("Weekly Expiry (YYYY-MM-DD)", value="2026-01-25")

placeholder = st.empty()

REFRESH_INTERVAL = 15

while True:
    if access_token:
        try:
            data = get_option_chain(access_token, expiry)
            spot = data["spotPrice"]

            signal, strike = find_signal(data, spot)

            with placeholder.container():
                st.metric("NIFTY Spot", spot)
                st.metric("Signal", signal)
                if strike:
                    st.metric("Strike", strike)

                st.subheader("Top Strikes")
                st.dataframe([
                    {
                        "Strike": s["strikePrice"],
                        "CE OI": s["call"]["oi"],
                        "CE Δ": s["call"]["delta"],
                        "CE ΔOI": s["call"]["oiChange"],
                        "PE OI": s["put"]["oi"],
                        "PE Δ": s["put"]["delta"],
                        "PE ΔOI": s["put"]["oiChange"],
                    }
                    for s in data["data"]
                ])

        except Exception as e:
            st.error(str(e))

    time.sleep(REFRESH_INTERVAL)
