import requests

BASE_URL = "https://api.dhan.co/v2"

def get_option_chain(access_token, expiry):
    url = f"{BASE_URL}/optionchain"
    
    headers = {
        "access-token": access_token,
        "Content-Type": "application/json"
    }

    payload = {
        "symbol": "NIFTY",
        "exchangeSegment": "NSE_FNO",
        "expiry": expiry
    }

    r = requests.post(url, json=payload, headers=headers)
    return r.json()
