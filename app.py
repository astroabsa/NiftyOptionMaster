import streamlit as st
from dhanhq import dhanhq
from datetime import datetime, timedelta
import time
import pandas as pd
import numpy as np
import pytz

# ---------------------------------------------------------
# 1. PAGE CONFIG
# ---------------------------------------------------------
st.set_page_config(page_title="Nifty Gamma Debugger", page_icon="🛠️", layout="wide")
IST = pytz.timezone('Asia/Kolkata')

# Initialize Session
if 'log_df' not in st.session_state:
    st.session_state.log_df = pd.DataFrame(columns=[
        "Timestamp", "Spot", "EMA_5", "RSI", "Buildup", "Signal"
    ])
if 'hist_data' not in st.session_state:
    st.session_state.hist_data = pd.DataFrame()

st.title("🛠️ Debug Mode: Nifty Gamma Hunter")

# ---------------------------------------------------------
# 2. DEBUG: CHECK SECRETS
# ---------------------------------------------------------
st.write("### 1. Checking Credentials...")
try:
    CLIENT_ID = st.secrets["dhan"]["client_id"]
    ACCESS_TOKEN = st.secrets["dhan"]["access_token"]
    st.success(f"✅ Credentials Found! Client ID ends in: ...{str(CLIENT_ID)[-4:]}")
except Exception as e:
    st.error(f"❌ Secrets Error: {e}")
    st.stop()

# Config
SECURITY_ID = "13"          # NIFTY
EXCHANGE_SEGMENT = "IDX_I" 
INSTRUMENT_TYPE = "INDEX"

# Initialize API
try:
    dhan = dhanhq(CLIENT_ID, ACCESS_TOKEN)
except Exception as e:
    st.error(f"❌ API Init Failed: {e}")
    st.stop()

# ---------------------------------------------------------
# 3. HELPER FUNCTIONS (ROBUST)
# ---------------------------------------------------------
def calculate_rsi(series, period=14):
    if len(series) < period: return 50 # Default if not enough data
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/period, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/period, adjust=False).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def fetch_intraday_data():
    st.write("### 2. Fetching Historical Data...")
    try:
        now = datetime.now(IST)
        from_date = (now - timedelta(days=5)).strftime("%Y-%m-%d")
        to_date = now.strftime("%Y-%m-%d")
        
        # DEBUG PRINT
        st.caption(f"Requesting data from {from_date} to {to_date}")
        
        resp = dhan.intraday_minute_data(
            security_id=SECURITY_ID,
            exchange_segment=EXCHANGE_SEGMENT,
            instrument_type=INSTRUMENT_TYPE,
            from_date=from_date,
            to_date=to_date
        )
        
        if resp['status'] != 'success':
            st.warning(f"⚠️ History Fetch Failed: {resp}")
            return None
        
        data = resp['data']
        if not data:
            st.warning("⚠️ History Data is Empty!")
            return None
            
        df = pd.DataFrame(data)
        st.success(f"✅ Historical Data Loaded: {len(df)} candles found.")
        return df['close'].astype(float)
    except Exception as e:
        st.error(f"❌ History Exception: {e}")
        return None

def get_market_analysis():
    # 1. History
    if st.session_state.hist_data.empty:
        hist_prices = fetch_intraday_data()
        if hist_prices is not None:
            st.session_state.hist_data = hist_prices
    
    # 2. Expiry
    st.write("### 3. Fetching Expiry & Option Chain...")
    expiry = None
    try:
        # Note: Converting ID to int just in case
        ex_resp = dhan.expiry_list(int(SECURITY_ID), EXCHANGE_SEGMENT)
        
        if ex_resp['status'] != 'success':
            st.error(f"❌ Expiry Fetch Failed: {ex_resp}")
            return None
            
        dates = list(ex_resp['data']) if isinstance(ex_resp['data'], list) else list(ex_resp['data'].keys())
        expiry = sorted([d for d in dates if str(d).count('-')==2])[0]
        st.success(f"✅ Nearest Expiry: {expiry}")
        
        # 3. Option Chain
        oc_resp = dhan.option_chain(int(SECURITY_ID), EXCHANGE_SEGMENT, expiry)
        if oc_resp['status'] != 'success':
            st.error(f"❌ Option Chain Failed: {oc_resp}")
            return None
            
        raw = oc_resp.get('data', {})
        final_data = raw.get('data', raw) if 'data' in raw else raw
        oc = final_data.get('oc', {})
        ltp = final_data.get('last_price', 0)
        
        st.success(f"✅ Data Fetched! LTP: {ltp}")
        
    except Exception as e:
        st.error(f"❌ Market Data Exception: {e}")
        return None

    if ltp == 0: 
        st.warning("⚠️ LTP is 0. Market might be closed.")
        return None

    # Update History
    new_price_series = pd.Series([ltp])
    full_price_series = pd.concat([st.session_state.hist_data, new_price_series], ignore_index=True)
    if len(full_price_series) > 500: full_price_series = full_price_series.iloc[-500:]
    st.session_state.hist_data = full_price_series

    # Indicators
    ema_5 = full_price_series.ewm(span=5, adjust=False).mean().iloc[-1]
    rsi_series = calculate_rsi(full_price_series)
    rsi = rsi_series.iloc[-1] if not rsi_series.empty else 50

    # Gamma Levels
    max_ce_oi = 0
    max_pe_oi = 0
    ce_res_strike = 0
    pe_sup_strike = 0
    
    for key, data in oc.items():
        try:
            strike = float(key)
            ce_oi = data.get('ce', {}).get('oi', 0)
            pe_oi = data.get('pe', {}).get('oi', 0)
            if ce_oi > max_ce_oi:
                max_ce_oi = ce_oi
                ce_res_strike = strike
            if pe_oi > max_pe_oi:
                max_pe_oi = pe_oi
                pe_sup_strike = strike
        except: continue

    # OI Buildup
    strikes = sorted([(float(k), k) for k in oc.keys()])
    atm_tuple = min(strikes, key=lambda x: abs(x[0] - ltp))
    atm_idx = strikes.index(atm_tuple)
    selected = strikes[max(0, atm_idx - 3) : min(len(strikes), atm_idx + 4)]
    
    total_ce_chg = 0
    total_pe_chg = 0
    for val, key in selected:
        d = oc[key]
        total_ce_chg += (d.get('ce', {}).get('oi', 0) - d.get('ce', {}).get('previous_oi', 0))
        total_pe_chg += (d.get('pe', {}).get('oi', 0) - d.get('pe', {}).get('previous_oi', 0))
    
    net_oi_chg = total_pe_chg - total_ce_chg 

    # Logic
    buildup = "Neutral"
    price_chg = full_price_series.iloc[-1] - full_price_series.iloc[-2] if len(full_price_series) > 1 else 0
    
    if price_chg > 0 and net_oi_chg > 0: buildup = "Long Buildup (Strong) 🐂"
    elif price_chg > 0 and net_oi_chg < 0: buildup = "Short Covering (Weak) 👻"
    elif price_chg < 0 and net_oi_chg < 0: buildup = "Short Buildup (Strong) 🐻"
    elif price_chg < 0 and net_oi_chg > 0: buildup = "Long Unwinding (Weak) 📉"

    signal = "WAIT"
    color = "gray"
    
    if ltp > ema_5 and rsi > 55 and "Long" in buildup:
        signal = "SCALP BUY 🚀"
        color = "green"
    elif ltp > ema_5 and "Short Covering" in buildup:
        signal = "BUY (Caution: Covering)"
        color = "lightgreen"
    elif ltp < ema_5 and rsi < 45 and "Short" in buildup:
        signal = "SCALP SELL 🩸"
        color = "red"
        
    gamma_msg = "Safe Zone"
    if abs(ltp - ce_res_strike) < 20: gamma_msg = f"⚠️ Near Call Wall ({ce_res_strike})"
    if abs(ltp - pe_sup_strike) < 20: gamma_msg = f"⚠️ Near Put Wall ({pe_sup_strike})"

    return {
        "time": datetime.now(IST).strftime("%H:%M:%S"),
        "ltp": ltp,
        "ema": round(ema_5, 2),
        "rsi": round(rsi, 2),
        "buildup": buildup,
        "signal": signal,
        "color": color,
        "gamma": gamma_msg,
        "res": ce_res_strike,
        "sup": pe_sup_strike
    }

# ---------------------------------------------------------
# 4. RUN ANALYSIS
# ---------------------------------------------------------
if st.button("🚀 Run Analysis"):
    st.rerun()

data = get_market_analysis()

if data:
    st.write("### 4. Analysis Results")
    
    # Update Logs
    new_row = {
        "Timestamp": data['time'], "Spot": data['ltp'], "EMA_5": data['ema'],
        "RSI": data['rsi'], "Buildup": data['buildup'], "Signal": data['signal']
    }
    if st.session_state.log_df.empty or st.session_state.log_df.iloc[-1]['Timestamp'] != data['time']:
        st.session_state.log_df = pd.concat([st.session_state.log_df, pd.DataFrame([new_row])], ignore_index=True)

    # UI
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Spot", data['ltp'])
    c2.metric("RSI", data['rsi'])
    c3.metric("EMA-5", data['ema'])
    c4.metric("Cycle", data['buildup'])

    st.markdown(f"""
    <div style="padding: 20px; border: 2px solid {data['color']}; border-radius: 10px; text-align: center;">
        <h1 style="color: {data['color']}">{data['signal']}</h1>
        <p>{data['gamma']}</p>
    </div>
    """, unsafe_allow_html=True)
    
    st.dataframe(st.session_state.log_df.sort_index(ascending=False), use_container_width=True)

# Auto-Refresh Countdown
st.divider()
st.caption("Auto-refreshing in 180s...")
time.sleep(180)
st.rerun()
