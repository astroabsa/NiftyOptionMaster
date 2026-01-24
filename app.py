import streamlit as st
import time
from dhan_api import get_option_chain
from logic import find_signal
from expiry import get_next_weekly_expiry

st.set_page_config(page_title="NIFTY Option Scanner", layout="wide")

st.title("📊 NIFTY Weekly Option Scanner")

ACCESS_TOKEN = st.secrets["DHAN_ACCESS_TOKEN"]
expiry = get_next_nifty_expiry()

st.info(f"Monitoring Expiry: {expiry}")

placeholder = st.empty()
REFRESH_INTERVAL = 15

while True:
    try:
        data = get_option_chain(ACCESS_TOKEN, expiry)
        spot = data["data"]["underlyingValue"]
        signal, strike = find_signal(data, spot)

        with placeholder.container():
            st.metric("NIFTY Spot", spot)
            st.metric("Signal", signal)
            if strike:
                st.metric("Strike", strike)

            st.subheader("Option Chain Snapshot")
            st.dataframe([
                {
                    "Strike": s["strikePrice"],
                    "CE OI": s["ce"]["oi"],
                    "CE Δ": s["ce"]["delta"],
                    "CE ΔOI": s["ce"]["oiChange"],
                    "PE OI": s["pe"]["oi"],
                    "PE Δ": s["pe"]["delta"],
                    "PE ΔOI": s["pe"]["oiChange"],
                }
                for s in data["data"]["oc"]
            ])

    except Exception as e:
        st.error(str(e))

    time.sleep(REFRESH_INTERVAL)
