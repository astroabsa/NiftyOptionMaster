import streamlit as st
from dhanhq import dhanhq
import pandas as pd

st.set_page_config(page_title="Dhan API Diagnostic", page_icon="🩺")
st.title("🩺 Expiry Data Inspector")

# 1. Credentials
try:
    CLIENT_ID = st.secrets["dhan"]["client_id"]
    ACCESS_TOKEN = st.secrets["dhan"]["access_token"]
except:
    st.error("Secrets not found.")
    st.stop()

dhan = dhanhq(CLIENT_ID, ACCESS_TOKEN)

# 2. Config options to try
# Sometimes Nifty is ID 13, sometimes it behaves differently based on segment
configs_to_test = [
    {"id": "13", "seg": "IDX_I", "name": "NIFTY Index (IDX_I)"},
    {"id": "13", "seg": "NSE_FNO", "name": "NIFTY FNO (NSE_FNO)"}, 
]

st.write("Testing connectivity to Dhan API...")

for conf in configs_to_test:
    st.divider()
    st.subheader(f"Testing: {conf['name']}")
    
    try:
        # Try finding expiry list
        resp = dhan.expiry_list(security_id=conf['id'], exchange_segment=conf['seg'])
        
        if resp['status'] != 'success':
            st.error(f"❌ API Error: {resp}")
            continue
            
        data = resp.get('data', [])
        
        st.write("**Raw API Response:**")
        st.json(data) # <--- THIS IS WHAT WE NEED TO SEE
        
        # Check if list is empty
        if not data:
            st.warning("⚠️ Received Success status but Data is EMPTY.")
            continue
            
        # Try to parse dates
        raw_dates = list(data) if isinstance(data, list) else list(data.keys())
        st.write(f"Found {len(raw_dates)} raw entries.")
        
        valid_dates = sorted([d for d in raw_dates if str(d).count('-') == 2])
        
        if valid_dates:
            st.success(f"✅ VALID DATES FOUND: {valid_dates[:3]} ...")
        else:
            st.error("❌ No dates matched 'YYYY-MM-DD' format.")
            st.write(f"First 5 raw items: {raw_dates[:5]}")

    except Exception as e:
        st.error(f"Exception: {e}")
