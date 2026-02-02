import streamlit as st
from dhanhq import dhanhq
from datetime import datetime, timedelta
import time
import pandas as pd
import numpy as np
import pytz  # Library for Timezone handling

# ---------------------------------------------------------
# 1. PAGE CONFIG & SESSION
# ---------------------------------------------------------
st.set_page_config(page_title="Nifty Instant Tracker", page_icon="⚡", layout="wide")

# Define India Timezone
IST = pytz.timezone('Asia/Kolkata')

# Initialize Session State
if 'log_df' not in st.session_state:
    st.session_state.log_df = pd.DataFrame(columns=[
        "Timestamp", "Spot", "EMA_9", "Net Diff", "OI_Slope", "Signal"
    ])
if 'historical_loaded' not in st.session_state:
    st.session_state.historical_loaded = False

# ---------------------------------------------------------
# 2. API CONNECTION
# ---------------------------------------------------------
try:
    CLIENT_ID = st.secrets["dhan"]["client_id"]
    ACCESS_TOKEN = st.secrets["dhan"]["access_token"]
except:
    st.error("🚨 Secrets not found! Check .streamlit/secrets.toml")
    st.stop()

SECURITY_ID = "13"          # NIFTY
EXCHANGE_SEGMENT = "IDX_I" 
INSTRUMENT_TYPE = "INDEX"
dhan = dhanhq(CLIENT_ID, ACCESS_TOKEN)

# ---------------------------------------------------------
# 3. CORE LOGIC
# ---------------------------------------------------------
def fetch_historical_trend():
    """
    Fetches today's intraday data to backfill EMA-9 Trend immediately.
    """
    try:
        # Dhan API request for Intraday Minute Data
        resp = dhan.intraday_minute_data(
            security_id=SECURITY_ID,
            exchange_segment=EXCHANGE_SEGMENT,
            instrument_type=INSTRUMENT_TYPE
        )
        
        if resp['status'] != 'success':
            st.warning("⚠️ Could not fetch historical data. Trend will build up live.")
            return None

        data = resp['data']
        if not data: return None

        # Convert to DataFrame
        df_hist = pd.DataFrame(data)
        
        # Calculate EMA-9 on this historical data
        df_hist['EMA_9'] = df_hist['close'].ewm(span=9, adjust=False).mean()
        
        last_ema = df_hist['EMA_9'].iloc[-1]
        
        return last_ema

    except Exception as e:
        st.warning(f"⚠️ Historical Data Error: {e}")
        return None

def get_nearest_expiry():
    try:
        resp = dhan.expiry_list(int(SECURITY_ID), EXCHANGE_SEGMENT)
        if resp['status'] != 'success': return None
        data = resp['data']
        dates = list(data) if isinstance(data, list) else []
        if isinstance(data, dict):
             for val in data.values():
                 if isinstance(val, list): dates = val; break
             if not dates: dates = list(data.keys())
        
        valid = sorted([d for d in dates if str(d).count('-')==2])
        return valid[0] if valid else None
    except: return None

def analyze_market():
    # --- 0. PRE-LOAD TREND (ONE TIME) ---
    current_ema = None
    if not st.session_state.historical_loaded:
        with st.spinner("Fetching historical trend..."):
            hist_ema = fetch_historical_trend()
            if hist_ema:
                st.session_state.historical_loaded = True
                current_ema = hist_ema
    
    expiry = get_nearest_expiry()
    if not expiry: return None

    oc_resp = dhan.option_chain(int(SECURITY_ID), EXCHANGE_SEGMENT, expiry)
    if oc_resp['status'] != 'success': return None

    raw = oc_resp.get('data', {})
    final_data = raw.get('data', raw) if 'data' in raw else raw
    oc = final_data.get('oc', {})
    ltp = final_data.get('last_price', 0)

    if ltp == 0 or not oc: return None

    # --- 1. PROCESS OI DATA ---
    strikes = sorted([(float(k), k) for k in oc.keys()])
    atm_tuple = min(strikes, key=lambda x: abs(x[0] - ltp))
    atm_idx = strikes.index(atm_tuple)
    
    selected = strikes[max(0, atm_idx - 5) : min(len(strikes), atm_idx + 6)]

    total_ce_chg = 0
    total_pe_chg = 0

    for val, key in selected:
        d = oc[key]
        ce_chg = d.get('ce', {}).get('oi', 0) - d.get('ce', {}).get('previous_oi', 0)
        pe_chg = d.get('pe', {}).get('oi', 0) - d.get('pe', {}).get('previous_oi', 0)
        total_ce_chg += ce_chg
        total_pe_chg += pe_chg

    net_diff = total_pe_chg - total_ce_chg 

    # --- 2. UPDATE LOGS & INDICATORS ---
    # FIX: Get current time in IST (GMT +5:30)
    timestamp = datetime.now(IST).strftime("%H:%M:%S")
    
    temp_df = st.session_state.log_df.copy()
    new_row = pd.DataFrame([{"Timestamp": timestamp, "Spot": ltp, "Net Diff": net_diff}])
    temp_df = pd.concat([temp_df, new_row], ignore_index=True)
    
    # A. Calculate EMA-9
    if len(temp_df) < 9 and current_ema:
        # Use historical EMA seed
        k = 2 / (9 + 1)
        calculated_ema = (ltp * k) + (current_ema * (1 - k))
    else:
        # Standard Calculation
        calculated_ema = temp_df['Spot'].ewm(span=9, adjust=False).mean().iloc[-1]
    
    trend = "BULLISH" if ltp > calculated_ema else "BEARISH"

    # B. Calculate OI Momentum (Slope)
    lookback = 3
    if len(temp_df) > lookback:
        past_diff = temp_df.iloc[-(lookback+1)]['Net Diff']
        oi_slope = net_diff - past_diff
    else:
        oi_slope = 0 

    slope_status = "POSITIVE" if oi_slope > 0 else "NEGATIVE"

    # --- 3. SIGNAL LOGIC ---
    signal = "WAIT ⏳"
    color = "gray"

    if oi_slope == 0:
        signal = "Building History... (Wait 3m)"
    elif trend == "BULLISH" and slope_status == "POSITIVE":
        signal = "STRONG BUY 🚀"
        color = "green"
    elif trend == "BEARISH" and slope_status == "NEGATIVE":
        signal = "STRONG SELL 🩸"
        color = "red"
    elif trend == "BULLISH" and slope_status == "NEGATIVE":
        signal = "DIVERGENCE ⚠️ (Price Up, OI Weak)"
        color = "orange"
    elif trend == "BEARISH" and slope_status == "POSITIVE":
        signal = "DIVERGENCE ⚠️ (Price Down, OI Strong)"
        color = "orange"

    return {
        "timestamp": timestamp,
        "expiry": expiry,
        "ltp": ltp,
        "ema": round(calculated_ema, 2),
        "net_diff": net_diff,
        "oi_slope": oi_slope,
        "signal": signal,
        "color": color,
        "trend_label": trend
    }

# ---------------------------------------------------------
# 4. UI LAYOUT
# ---------------------------------------------------------
st.title("⚡ Nifty Instant Momentum Scalper")
st.markdown("*(Trend: EMA-9 on Historical Data | Momentum: Live OI Slope)*")

if st.button("🔄 Refresh"):
    st.rerun()

data = analyze_market()

if data:
    # Update Session Log
    new_entry = {
        "Timestamp": data['timestamp'],
        "Spot": data['ltp'],
        "EMA_9": data['ema'],
        "Net Diff": data['net_diff'],
        "OI_Slope": data['oi_slope'],
        "Signal": data['signal']
    }
    
    if st.session_state.log_df.empty or st.session_state.log_df.iloc[-1]['Timestamp'] != data['timestamp']:
        st.session_state.log_df = pd.concat([st.session_state.log_df, pd.DataFrame([new_entry])], ignore_index=True)

    # METRICS
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Spot Price", f"{data['ltp']}", f"Trend: {data['trend_label']}")
    
    diff_cr = data['net_diff'] / 10000000
    slope_lk = data['oi_slope'] / 100000
    
    c2.metric("Net OI Diff", f"{diff_cr:.2f} Cr")
    c3.metric("OI Momentum", f"{slope_lk:.2f} Lk", delta=slope_lk)
    c4.metric("Expiry", data['expiry'])

    # SIGNAL BANNER
    st.markdown(f"""
    <div style="padding: 15px; border: 2px solid {data['color']}; border-radius: 10px; text-align: center; background: #1e1e1e;">
        <h2 style="color: {data['color']}; margin:0;">{data['signal']}</h2>
        <p style="color: white; margin:0;">EMA: {data['ema']} | Spot: {data['ltp']}</p>
    </div>
    """, unsafe_allow_html=True)

    # DATA TABLE
    tab1, tab2 = st.tabs(["📊 Live Log", "📈 Explanation"])
    with tab1:
        st.dataframe(st.session_state.log_df.sort_index(ascending=False), use_container_width=True)
    with tab2:
        st.markdown("""
        **Strategy:**
        1. **Instant Trend:** We fetch today's price history on startup to calculate EMA-9 immediately.
        2. **OI Momentum:** We still need ~3-6 mins of live data to calculate the "Slope" (Rate of Change).
        3. **Signal:** We only trade when **Price Trend** and **OI Momentum** agree.
        """)

time.sleep(180)
st.rerun()
