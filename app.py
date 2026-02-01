import streamlit as st
from dhanhq import dhanhq
from datetime import datetime
import time
import pandas as pd
import numpy as np

# ---------------------------------------------------------
# 1. PAGE CONFIG & SESSION
# ---------------------------------------------------------
st.set_page_config(page_title="Nifty Momentum Tracker", page_icon="🚀", layout="wide")

if 'log_df' not in st.session_state:
    st.session_state.log_df = pd.DataFrame(columns=[
        "Timestamp", "Spot", "EMA_9", "Net Diff", "OI_Slope", "Signal"
    ])

# ---------------------------------------------------------
# 2. API CONNECTION
# ---------------------------------------------------------
try:
    CLIENT_ID = st.secrets["dhan"]["client_id"]
    ACCESS_TOKEN = st.secrets["dhan"]["access_token"]
except:
    st.error("🚨 Secrets not found! Check .streamlit/secrets.toml")
    st.stop()

SECURITY_ID = 13          # NIFTY
EXCHANGE_SEGMENT = "IDX_I" 
dhan = dhanhq(CLIENT_ID, ACCESS_TOKEN)

# ---------------------------------------------------------
# 3. CORE LOGIC
# ---------------------------------------------------------
def get_nearest_expiry():
    try:
        resp = dhan.expiry_list(SECURITY_ID, EXCHANGE_SEGMENT)
        if resp['status'] != 'success': return None
        data = resp['data']
        # Handle list vs dict format
        dates = list(data) if isinstance(data, list) else []
        if isinstance(data, dict):
             for val in data.values():
                 if isinstance(val, list): dates = val; break
             if not dates: dates = list(data.keys())
        
        valid = sorted([d for d in dates if str(d).count('-')==2])
        return valid[0] if valid else None
    except: return None

def calculate_ema(prices, period=9):
    if len(prices) < period: return prices[-1] # Not enough data, return current
    return pd.Series(prices).ewm(span=period, adjust=False).mean().iloc[-1]

def analyze_market():
    expiry = get_nearest_expiry()
    if not expiry: return None

    oc_resp = dhan.option_chain(SECURITY_ID, EXCHANGE_SEGMENT, expiry)
    if oc_resp['status'] != 'success': return None

    # Unwrap Data
    raw = oc_resp.get('data', {})
    final_data = raw.get('data', raw) if 'data' in raw else raw
    oc = final_data.get('oc', {})
    ltp = final_data.get('last_price', 0)

    if ltp == 0 or not oc: return None

    # --- 1. PROCESS OI DATA ---
    strikes = sorted([(float(k), k) for k in oc.keys()])
    atm_tuple = min(strikes, key=lambda x: abs(x[0] - ltp))
    atm_idx = strikes.index(atm_tuple)
    
    # Focus on ATM +/- 5 Strikes (Tighter focus for momentum)
    selected = strikes[max(0, atm_idx - 5) : min(len(strikes), atm_idx + 6)]

    total_ce_chg = 0
    total_pe_chg = 0

    for val, key in selected:
        d = oc[key]
        ce_chg = d.get('ce', {}).get('oi', 0) - d.get('ce', {}).get('previous_oi', 0)
        pe_chg = d.get('pe', {}).get('oi', 0) - d.get('pe', {}).get('previous_oi', 0)
        total_ce_chg += ce_chg
        total_pe_chg += pe_chg

    net_diff = total_pe_chg - total_ce_chg # Positive = Bullish, Negative = Bearish

    # --- 2. UPDATE HISTORY & CALCULATE INDICATORS ---
    timestamp = datetime.now().strftime("%H:%M:%S")
    
    # Add temporary row to calculate indicators
    temp_df = st.session_state.log_df.copy()
    new_row = {"Timestamp": timestamp, "Spot": ltp, "Net Diff": net_diff}
    # Use pandas concat instead of append
    temp_df = pd.concat([temp_df, pd.DataFrame([new_row])], ignore_index=True)
    
    # A. Calculate EMA-9 Trend
    current_ema = calculate_ema(temp_df['Spot'].tolist(), period=9)
    trend = "BULLISH" if ltp > current_ema else "BEARISH"

    # B. Calculate OI Momentum (Slope)
    # Compare current Net Diff with 3 periods ago (approx 9-10 mins)
    lookback = 3
    if len(temp_df) > lookback:
        past_diff = temp_df.iloc[-(lookback+1)]['Net Diff']
        oi_slope = net_diff - past_diff
    else:
        oi_slope = 0 # Not enough data yet

    slope_status = "POSITIVE" if oi_slope > 0 else "NEGATIVE"

    # --- 3. GENERATE SIGNAL ---
    signal = "WAIT ⏳"
    color = "gray"

    # Rule: Price must be above EMA AND OI Slope must be Positive
    if trend == "BULLISH" and slope_status == "POSITIVE":
        signal = "STRONG BUY 🚀"
        color = "green"
    elif trend == "BEARISH" and slope_status == "NEGATIVE":
        signal = "STRONG SELL 🩸"
        color = "red"
    elif trend == "BULLISH" and slope_status == "NEGATIVE":
        signal = "DIVERGENCE (Price Up, OI Weak) ⚠️"
        color = "orange"
    elif trend == "BEARISH" and slope_status == "POSITIVE":
        signal = "DIVERGENCE (Price Down, OI Strong) ⚠️"
        color = "orange"

    return {
        "timestamp": timestamp,
        "expiry": expiry,
        "ltp": ltp,
        "ema": round(current_ema, 2),
        "net_diff": net_diff,
        "oi_slope": oi_slope,
        "signal": signal,
        "color": color,
        "trend_label": trend
    }

# ---------------------------------------------------------
# 4. UI LAYOUT
# ---------------------------------------------------------
st.title("⚡ Nifty OI Momentum Scalper")
st.markdown("*(Refreshes every 3 mins. Trend based on EMA-9. Momentum based on 10-min Change)*")

if st.button("🔄 Refresh Now"):
    st.rerun()

data = analyze_market()

if data:
    # Append to Session State Log
    new_entry = {
        "Timestamp": data['timestamp'],
        "Spot": data['ltp'],
        "EMA_9": data['ema'],
        "Net Diff": data['net_diff'],
        "OI_Slope": data['oi_slope'],
        "Signal": data['signal']
    }
    
    # Prevent duplicate logging on manual refresh
    if st.session_state.log_df.empty or st.session_state.log_df.iloc[-1]['Timestamp'] != data['timestamp']:
        st.session_state.log_df = pd.concat([st.session_state.log_df, pd.DataFrame([new_entry])], ignore_index=True)

    # METRICS
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Spot Price", f"{data['ltp']}", f"{data['ltp'] - data['ema']:.2f} vs EMA")
    
    # Format large numbers for Net Diff
    diff_cr = data['net_diff'] / 10000000
    slope_lk = data['oi_slope'] / 100000
    
    c2.metric("Net OI Diff", f"{diff_cr:.2f} Cr")
    c3.metric("OI Momentum (10m)", f"{slope_lk:.2f} Lk", delta=slope_lk)
    c4.metric("Expiry", data['expiry'])

    # SIGNAL BANNER
    st.markdown(f"""
    <div style="padding: 15px; border: 2px solid {data['color']}; border-radius: 10px; text-align: center; background: #1e1e1e;">
        <h2 style="color: {data['color']}; margin:0;">{data['signal']}</h2>
        <p style="color: white; margin:0;">Trend: {data['trend_label']} | OI Slope: {data['oi_slope']:,.0f}</p>
    </div>
    """, unsafe_allow_html=True)

    # TABLES
    tab1, tab2 = st.tabs(["📊 Live Log", "📈 Explanation"])
    
    with tab1:
        # Show Log with styling
        display_df = st.session_state.log_df.copy().sort_index(ascending=False)
        st.dataframe(display_df, use_container_width=True)
        
        # Download
        csv = display_df.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Download CSV", csv, "oi_momentum_log.csv", "text/csv")

    with tab2:
        st.markdown("""
        ### How to read this?
        1. **OI Momentum:** This is the *Change in Net Diff* over the last ~10 mins. 
           - If Net Diff is -1.5Cr but Momentum is +20L, it means **Short Covering** (Bullish).
        2. **EMA-9:** A dynamic line that filters out small choppy moves.
        3. **Logic:**
           - We **BUY** only if Price is above EMA AND Momentum is Positive.
           - We **SELL** only if Price is below EMA AND Momentum is Negative.
           - Anything else is a **TRAP/WAIT**.
        """)

# Auto-Refresh
time.sleep(180)
st.rerun()
