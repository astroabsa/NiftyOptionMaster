import streamlit as st
from dhanhq import dhanhq
from datetime import datetime, timedelta
import time
import pandas as pd
import numpy as np
import pytz

# ---------------------------------------------------------
# 1. PAGE CONFIG & SESSION
# ---------------------------------------------------------
st.set_page_config(page_title="Nifty Gamma Hunter", page_icon="🎯", layout="wide")
IST = pytz.timezone('Asia/Kolkata')

if 'log_df' not in st.session_state:
    st.session_state.log_df = pd.DataFrame(columns=[
        "Timestamp", "Spot", "EMA_5", "RSI", "Buildup", "Signal"
    ])
if 'hist_data' not in st.session_state:
    st.session_state.hist_data = pd.DataFrame()

# ---------------------------------------------------------
# 2. CONFIGURATION
# ---------------------------------------------------------
try:
    CLIENT_ID = st.secrets["dhan"]["client_id"]
    ACCESS_TOKEN = st.secrets["dhan"]["access_token"]
except:
    st.error("🚨 Secrets not found! Check .streamlit/secrets.toml")
    st.stop()

dhan = dhanhq(CLIENT_ID, ACCESS_TOKEN)

# --- CONFIG ---
SPOT_ID = "13"          # NIFTY 50
SPOT_SEGMENT = "IDX_I"  

# ---------------------------------------------------------
# 3. SELF-HEALING DATA FETCHER
# ---------------------------------------------------------
def fetch_intraday_data():
    """Fetches Spot Price History."""
    try:
        now = datetime.now(IST)
        from_date = (now - timedelta(days=5)).strftime("%Y-%m-%d")
        to_date = now.strftime("%Y-%m-%d")
        
        resp = dhan.intraday_minute_data(
            security_id=SPOT_ID,
            exchange_segment=SPOT_SEGMENT,
            instrument_type="INDEX",
            from_date=from_date,
            to_date=to_date
        )
        
        if resp['status'] != 'success': return None
        data = resp['data']
        if not data: return None
        
        df = pd.DataFrame(data)
        return df['close'].astype(float)
    except:
        return None

def find_valid_expiry_and_chain():
    """
    1. Tries all segments to find a list of dates.
    2. Tests dates until one returns a valid Option Chain.
    """
    possible_segments = ["NSE_FNO", "IDX_I", "NSE_IDX"]
    found_dates = []

    # A. Find the Date List
    for seg in possible_segments:
        try:
            resp = dhan.expiry_list(under_security_id=int(SPOT_ID), under_exchange_segment=seg)
            if resp['status'] == 'success' and resp['data']:
                raw = list(resp['data']) if isinstance(resp['data'], list) else list(resp['data'].keys())
                # Filter valid YYYY-MM-DD
                found_dates = sorted([d for d in raw if str(d).count('-')==2])
                if found_dates:
                    break # Stop looking if we found dates
        except: continue
    
    if not found_dates:
        # Emergency Fallback: If API list fails, try manually calculated dates
        today = datetime.now().date()
        # Try next 7 days
        found_dates = [str(today + timedelta(days=i)) for i in range(7)]

    # B. Test Dates against Option Chain (The "811 Error" Killer)
    for test_date in found_dates:
        # Ignore past dates
        try:
            if datetime.strptime(str(test_date), "%Y-%m-%d").date() < datetime.now().date():
                continue
        except: continue

        try:
            # Try fetching chain with this date
            oc_resp = dhan.option_chain(
                under_security_id=int(SPOT_ID),
                under_exchange_segment="NSE_FNO", # Chain is ALWAYS NSE_FNO
                expiry=test_date
            )
            
            if oc_resp['status'] == 'success':
                # IT WORKS! Return this valid data
                return test_date, oc_resp
            
            # If 811 or Failure, loop to next date...
        except: continue

    return None, None

def analyze_gamma_levels(oc):
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
        
    return ce_res_strike, pe_sup_strike

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/period, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/period, adjust=False).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

# ---------------------------------------------------------
# 4. MAIN ANALYSIS
# ---------------------------------------------------------
def get_market_analysis():
    # 1. Update History
    if st.session_state.hist_data.empty:
        hist_prices = fetch_intraday_data()
        if hist_prices is not None:
            st.session_state.hist_data = hist_prices

    # 2. Get Valid Chain (Self-Healing)
    expiry, oc_resp = find_valid_expiry_and_chain()
    
    if not expiry or not oc_resp:
        st.error("❌ Critical: Could not find ANY valid expiry date for NIFTY.")
        return None

    try:
        raw = oc_resp.get('data', {})
        final_data = raw.get('data', raw) if 'data' in raw else raw
        oc = final_data.get('oc', {})
        ltp = final_data.get('last_price', 0)
    except: return None

    if ltp == 0: return None

    # Update History
    new_price_series = pd.Series([ltp])
    full_price_series = pd.concat([st.session_state.hist_data, new_price_series], ignore_index=True)
    if len(full_price_series) > 500: full_price_series = full_price_series.iloc[-500:]
    st.session_state.hist_data = full_price_series

    # 3. Indicators
    ema_5 = full_price_series.ewm(span=5, adjust=False).mean().iloc[-1]
    rsi_series = calculate_rsi(full_price_series)
    rsi = rsi_series.iloc[-1]

    # 4. Gamma & Cycle
    res, sup = analyze_gamma_levels(oc)
    
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

    # 5. Signal Logic
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
        signal = "BUY (Caution)"
        color = "lightgreen"
    elif ltp < ema_5 and rsi < 45 and "Short" in buildup:
        signal = "SCALP SELL 🩸"
        color = "red"
        
    gamma_msg = "Safe Zone"
    if abs(ltp - res) < 20: gamma_msg = f"⚠️ Near Call Wall ({res})"
    if abs(ltp - sup) < 20: gamma_msg = f"⚠️ Near Put Wall ({sup})"

    return {
        "time": datetime.now(IST).strftime("%H:%M:%S"),
        "expiry": expiry,
        "ltp": ltp,
        "ema": round(ema_5, 2),
        "rsi": round(rsi, 2),
        "buildup": buildup,
        "signal": signal,
        "color": color,
        "gamma": gamma_msg,
        "res": res,
        "sup": sup
    }

# ---------------------------------------------------------
# 5. DASHBOARD
# ---------------------------------------------------------
st.title("🎯 Nifty Gamma Hunter")

if st.button("🔄 Refresh Now"):
    st.rerun()

data = get_market_analysis()

if data:
    new_row = {
        "Timestamp": data['time'], "Spot": data['ltp'], "EMA_5": data['ema'],
        "RSI": data['rsi'], "Buildup": data['buildup'], "Signal": data['signal']
    }
    if st.session_state.log_df.empty or st.session_state.log_df.iloc[-1]['Timestamp'] != data['time']:
        st.session_state.log_df = pd.concat([st.session_state.log_df, pd.DataFrame([new_row])], ignore_index=True)

    # Info Bar
    st.info(f"Using Expiry: **{data['expiry']}**")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Spot Price", data['ltp'], f"{data['ltp']-data['ema']:.1f} vs EMA")
    c2.metric("RSI", data['rsi'])
    c3.metric("Call Wall", data['res'])
    c4.metric("Put Wall", data['sup'])

    st.markdown(f"""
    <div style="padding: 20px; background: #262730; border-radius: 10px; border: 2px solid {data['color']}; text-align: center;">
        <h1 style="color: {data['color']}; margin:0;">{data['signal']}</h1>
        <h3 style="color: white; margin:5px;">{data['buildup']}</h3>
        <p style="color: yellow; font-weight: bold;">{data['gamma']}</p>
    </div>
    """, unsafe_allow_html=True)

    with st.expander("📜 Logs", expanded=True):
        st.dataframe(st.session_state.log_df.sort_index(ascending=False), use_container_width=True)
    
    st.download_button("📥 Download Log", st.session_state.log_df.to_csv(index=False).encode('utf-8'), "gamma_log.csv")

st.divider()
st.caption("Auto-refreshing in 180s...")
progress_bar = st.progress(0)
for i in range(180):
    time.sleep(1)
    progress_bar.progress((i + 1) / 180)
st.rerun()
