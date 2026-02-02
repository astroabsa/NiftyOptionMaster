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
    st.error("🚨 Secrets not found!")
    st.stop()

SECURITY_ID = "13"          # NIFTY
EXCHANGE_SEGMENT = "IDX_I" 
INSTRUMENT_TYPE = "INDEX"
dhan = dhanhq(CLIENT_ID, ACCESS_TOKEN)

# ---------------------------------------------------------
# 3. ADVANCED CALCULATIONS
# ---------------------------------------------------------
def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/period, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/period, adjust=False).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def fetch_intraday_data():
    """Fetches full intraday history for EMA-5 and RSI calculations."""
    try:
        now = datetime.now(IST)
        from_date = (now - timedelta(days=5)).strftime("%Y-%m-%d")
        to_date = now.strftime("%Y-%m-%d")
        
        resp = dhan.intraday_minute_data(
            security_id=SECURITY_ID,
            exchange_segment=EXCHANGE_SEGMENT,
            instrument_type=INSTRUMENT_TYPE,
            from_date=from_date,
            to_date=to_date
        )
        if resp['status'] != 'success': return None
        
        df = pd.DataFrame(resp['data'])
        # Rename for clarity if needed, assuming 'close' exists
        return df['close'].astype(float)
    except:
        return None

def analyze_gamma_levels(oc, ltp):
    """
    Identifies the 'Magnet' Strikes where Gamma is highest.
    """
    strikes = []
    max_ce_oi = 0
    max_pe_oi = 0
    ce_res_strike = 0
    pe_sup_strike = 0
    
    atm_strike_diff = float('inf')
    atm_strike = 0

    for key, data in oc.items():
        try:
            strike = float(key)
            ce_oi = data.get('ce', {}).get('oi', 0)
            pe_oi = data.get('pe', {}).get('oi', 0)
            
            # Find ATM
            if abs(strike - ltp) < atm_strike_diff:
                atm_strike_diff = abs(strike - ltp)
                atm_strike = strike

            # Find Major Resistance (Max CE OI)
            if ce_oi > max_ce_oi:
                max_ce_oi = ce_oi
                ce_res_strike = strike
                
            # Find Major Support (Max PE OI)
            if pe_oi > max_pe_oi:
                max_pe_oi = pe_oi
                pe_sup_strike = strike

        except: continue
        
    return atm_strike, ce_res_strike, pe_sup_strike

def get_market_analysis():
    # 1. Fetch Price History (One-time or Update)
    if st.session_state.hist_data.empty:
        hist_prices = fetch_intraday_data()
        if hist_prices is not None:
            st.session_state.hist_data = hist_prices

    # 2. Get Live Option Chain
    expiry = None
    try:
        ex_resp = dhan.expiry_list(int(SECURITY_ID), EXCHANGE_SEGMENT)
        dates = list(ex_resp['data']) if isinstance(ex_resp['data'], list) else list(ex_resp['data'].keys())
        expiry = sorted([d for d in dates if str(d).count('-')==2])[0]
        
        oc_resp = dhan.option_chain(int(SECURITY_ID), EXCHANGE_SEGMENT, expiry)
        raw = oc_resp.get('data', {})
        final_data = raw.get('data', raw) if 'data' in raw else raw
        oc = final_data.get('oc', {})
        ltp = final_data.get('last_price', 0)
    except: return None

    if ltp == 0: return None

    # Update History with Live LTP
    # Use loc index or concat to append
    new_price_series = pd.Series([ltp])
    full_price_series = pd.concat([st.session_state.hist_data, new_price_series], ignore_index=True)
    # Keep session data manageable (last 500 points)
    if len(full_price_series) > 500: full_price_series = full_price_series.iloc[-500:]
    st.session_state.hist_data = full_price_series

    # --- 3. CALCULATE INDICATORS ---
    # EMA-5 (Fast Trend)
    ema_5 = full_price_series.ewm(span=5, adjust=False).mean().iloc[-1]
    
    # RSI-14 (Momentum)
    rsi_series = calculate_rsi(full_price_series)
    rsi = rsi_series.iloc[-1]

    # --- 4. OI BUILDUP & GAMMA ---
    atm, res, sup = analyze_gamma_levels(oc, ltp)
    
    # Net OI Change (ATM +/- 3 strikes for pure momentum)
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
    
    net_oi_chg = total_pe_chg - total_ce_chg # Positive = Bullish

    # --- 5. DETERMINE SIGNAL ---
    # A. Cycle Identification
    buildup = "Neutral"
    price_chg = full_price_series.iloc[-1] - full_price_series.iloc[-2] if len(full_price_series) > 1 else 0
    
    if price_chg > 0 and net_oi_chg > 0: buildup = "Long Buildup (Strong) 🐂"
    elif price_chg > 0 and net_oi_chg < 0: buildup = "Short Covering (Weak) 👻"
    elif price_chg < 0 and net_oi_chg < 0: buildup = "Short Buildup (Strong) 🐻"
    elif price_chg < 0 and net_oi_chg > 0: buildup = "Long Unwinding (Weak) 📉"

    # B. The Signal
    signal = "WAIT"
    color = "gray"
    
    # Bullish Logic: Price > EMA-5 + RSI > 50 + Bullish Cycle
    if ltp > ema_5 and rsi > 55 and "Long" in buildup:
        signal = "SCALP BUY 🚀"
        color = "green"
    elif ltp > ema_5 and "Short Covering" in buildup:
        signal = "BUY (Caution: Covering)"
        color = "lightgreen"
        
    # Bearish Logic: Price < EMA-5 + RSI < 50 + Bearish Cycle
    elif ltp < ema_5 and rsi < 45 and "Short" in buildup:
        signal = "SCALP SELL 🩸"
        color = "red"
        
    # C. Gamma Warning
    gamma_msg = ""
    if abs(ltp - res) < 15: gamma_msg = f"⚠️ Near Call Wall ({res}). Possible Reversal or Blast."
    if abs(ltp - sup) < 15: gamma_msg = f"⚠️ Near Put Wall ({sup}). Possible Reversal or Blast."

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
# 4. UI
# ---------------------------------------------------------
st.title("🎯 Nifty Gamma Hunter (EMA-5 + RSI + Buildup)")

if st.button("🔄 Check Market"):
    st.rerun()

data = get_market_analysis()

if data:
    # Log
    new_row = {
        "Timestamp": data['time'], "Spot": data['ltp'], "EMA_5": data['ema'],
        "RSI": data['rsi'], "Buildup": data['buildup'], "Signal": data['signal']
    }
    if st.session_state.log_df.empty or st.session_state.log_df.iloc[-1]['Timestamp'] != data['time']:
        st.session_state.log_df = pd.concat([st.session_state.log_df, pd.DataFrame([new_row])], ignore_index=True)

    # Metrics
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Spot Price", data['ltp'], f"{data['ltp']-data['ema']:.1f} vs EMA-5")
    c2.metric("RSI (Momentum)", data['rsi'])
    c3.metric("Resistance (Max CE)", data['res'])
    c4.metric("Support (Max PE)", data['sup'])

    # Main Signal
    st.markdown(f"""
    <div style="padding: 20px; background: #262730; border-radius: 10px; border: 2px solid {data['color']}; text-align: center;">
        <h1 style="color: {data['color']}; margin:0;">{data['signal']}</h1>
        <h3 style="color: white; margin:5px;">{data['buildup']}</h3>
        <p style="color: yellow;">{data['gamma']}</p>
    </div>
    """, unsafe_allow_html=True)

    # Table
    st.dataframe(st.session_state.log_df.sort_index(ascending=False), use_container_width=True)
    
    csv = st.session_state.log_df.to_csv(index=False).encode('utf-8')
    st.download_button("📥 Download Log", csv, "gamma_log.csv")

time.sleep(180)
st.rerun()
