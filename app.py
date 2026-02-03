import streamlit as st
from dhanhq import dhanhq
import pandas as pd

st.set_page_config(page_title="Dhan Connection Doctor", page_icon="🩺")
st.title("🩺 Dhan API Connection Doctor")

# 1. Credentials
try:
    CLIENT_ID = st.secrets["dhan"]["client_id"]
    ACCESS_TOKEN = st.secrets["dhan"]["access_token"]
    st.success("✅ Credentials Found")
except:
    st.error("❌ Secrets missing.")
    st.stop()

dhan = dhanhq(CLIENT_ID, ACCESS_TOKEN)

# 2. Combinations to Test
tests = [
    {"id": "13", "seg": "IDX_I", "name": "NIFTY Spot (IDX_I)"},
    {"id": "13", "seg": "NSE_FNO", "name": "NIFTY FNO (NSE_FNO)"},
    {"id": "13", "seg": "NSE_IDX", "name": "NIFTY Index (NSE_IDX)"}, 
    {"id": "13", "seg": "NSE_EQ", "name": "NIFTY Equity (NSE_EQ)"},
]

st.write("---")
st.write("### 🔍 Testing Expiry Fetching...")

success_config = None

for t in tests:
    st.write(f"Testing: **{t['name']}**")
    try:
        # Check Expiry List
        resp = dhan.expiry_list(
            under_security_id=int(t['id']), 
            under_exchange_segment=t['seg']
        )
        
        status = resp.get('status', 'unknown')
        data = resp.get('data', [])
        
        if status == 'success' and data:
            st.success(f"✅ SUCCESS! Found {len(data)} dates.")
            st.json(data)
            success_config = t
            break  # Found the working one!
        elif status == 'success' and not data:
            st.warning("⚠️ Request OK, but Data is EMPTY.")
        else:
            st.error(f"❌ Failed. API Status: {status}")
            if 'remarks' in resp: st.caption(f"Error: {resp['remarks']}")
            
    except Exception as e:
        st.error(f"⚠️ Exception: {str(e)}")

st.write("---")

# 3. If found, test Option Chain with it
if success_config:
    st.write(f"### 🎯 Verifying Option Chain with {success_config['name']}...")
    try:
        # Get first date
        dates = list(resp['data'])
        expiry = sorted([d for d in dates if str(d).count('-')==2])[0]
        
        oc_resp = dhan.option_chain(
            under_security_id=int(success_config['id']),
            under_exchange_segment=success_config['seg'],
            expiry=expiry
        )
        
        if oc_resp['status'] == 'success':
            st.balloons()
            st.success(f"🎉 CONFIRMED! The correct segment is: `{success_config['seg']}`")
            st.info("Please update your main script with this segment.")
        else:
            st.error("❌ Option Chain Failed even with valid expiry.")
            st.json(oc_resp)
            
    except Exception as e:
        st.error(f"Test Failed: {e}")
else:
    st.error("🚫 All attempts failed. Please verify if 'NIFTY' (13) is accessible in your F&O plan.")
