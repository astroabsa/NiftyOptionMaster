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
st.set_page_config(page_title="Gamma Hunter (Force Mode)", page_icon="💪", layout="wide")
IST = pytz.timezone('Asia/Kolkata')

if 'log_df' not in st.session_state:
    st.session_state.log_df = pd.DataFrame(columns=[
        "Timestamp", "Spot", "EMA_5", "RSI", "Buildup", "Signal"
    ])
if 'hist_data' not in st.session_state:
    st.session_state.hist_data = pd.DataFrame()

# ---------------------------------------------------------
# 2. CONFIGURATION & SIDEBAR
# ---------------------------------------------------------
try:
    CLIENT_ID = st.secrets["dhan"]["client_id"]
    ACCESS_TOKEN = st.secrets["dhan"]["access_token"]
except:
    st.error("🚨 Secrets not found! Check .streamlit/secrets.toml")
    st.stop()

dhan = dhanhq(CLIENT_ID, ACCESS_TOKEN)

# --- SIDEBAR CONTROLS ---
st.sidebar.title("⚙️ Configuration")

# 1. Index Selector
index_choice = st.sidebar.radio("Select Index:", ["NIFTY 50", "FINNIFTY"], horizontal=True)

if index_choice == "NIFTY 50":
    SPOT_ID = "13"
    EXPIRY_DAY = 3  # Thursday
else:
    SPOT_ID = "25"  # FinNifty ID (Check your specific ID if different)
    EXPIRY_DAY = 1  # Tuesday

# 2. Date Force-Feeder
def get_math_expiry(target_weekday):
    """Calculates next specific weekday (0=Mon, 1=Tue, ... 3=Thu)"""
    today = datetime.now(IST).date()
    days_ahead = target_weekday - today.weekday()
    if days_ahead < 0: days_ahead += 7
    return today + timedelta(days=days_ahead)

calculated_date = get_math_expiry(EXPIRY_DAY)
expiry_date = st.sidebar.date_input("Force Expiry Date:", calculated_date)
st.sidebar.caption(f"Fetching data for: {expiry_date}")

# ---------------------------------------------------------
# 3. DATA FETCHING (NO VALIDATION CHECKS)
# ---------------------------------------------------------
def fetch_intraday_data():
    try:
        now = datetime.now(IST)
        from_date = (now - timedelta(days=5)).strftime("%Y-%m-%d")
        to_date = now.strftime("%Y-%m-%d")
        
        resp = dhan.intraday_minute_data(
            security_id=SPOT_ID,
            exchange_segment="IDX_I",
            instrument_type="INDEX",
            from_date=from_date,
            to_date=to_date
        )
        if resp['status'] != 'success': return None
        df = pd.DataFrame(resp['data'])
        return df['close'].astype(float)
    except: return None

def get_option_chain_forced():
    """
    Forcefully requests Option Chain for the selected date.
    Tries both segments (IDX_I and NSE_FNO) to handle API quirks.
    """
    date_str = str(expiry_date)
    
    # Attempt 1: Standard Method (Underlying is IDX_I)
    try:
        resp = dhan.option_chain(
            under_security_id=int(SPOT_ID),
            under_exchange_segment="IDX_I",
            expiry=date_str
        )
        if resp['status'] == 'success': return resp
    except: pass

    # Attempt 2: Fallback Method (Underlying is NSE_FNO - sometimes required)
    try:
        resp = dhan.option_chain(
            under_security_id=int(SPOT_ID),
            under_exchange_segment="NSE_FNO",
            expiry=date_str
        )
        if resp['status'] == 'success': return resp
    except: pass

    return None

# ---------------------------------------------------------
# 4. ANALYSIS LOGIC
# ---------------------------------------------------------
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

def get_market_analysis():
    # 1. History
    if st.session_state.hist_data.empty:
        hist_prices = fetch_intraday_data()
        if hist_prices is not None:
            st.session_state.hist_data = hist_prices

    # 2. Option Chain (FORCED)
    oc_resp = get_option_chain_forced()
    
    if not oc_resp:
        st.error(f"❌ Failed to fetch Option Chain for {expiry_date}. Market might be closed or date is invalid.")
        return None

    try:
        raw = oc_resp.get('data', {})
        final_data = raw.get('data', raw) if 'data' in raw else raw
        oc = final_data.get('oc', {})
        ltp = final_data.get('last_price', 0)
    except: return None

    if ltp == 0: 
        st.warning("⚠️ LTP is 0 (Market Closed?)")
        return None

    # Update History
    new_price_series = pd.Series([ltp])
    full_price_series = pd.concat([st.session_state.hist_data, new_price_series], ignore_index=True)
    if len(full_price_series) > 500: full_price_series = full_price_series.iloc[-500:]
    st.session_state.hist_data = full_price_series

    # Indicators
    ema_5 = full_price_series.ewm(span=5, adjust=False).mean().iloc[-1]
    rsi_series = calculate_rsi(full_price_series)
    rsi = rsi_series.iloc[-1]

    # Gamma
    res, sup = analyze_gamma_levels(oc)
    
    # Net OI
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

    # Signal Logic
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
st.title("💪 Gamma Hunter (Force Mode)")

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
