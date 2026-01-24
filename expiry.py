from datetime import datetime, timedelta

def get_next_nifty_expiry():
    today = datetime.now()
    weekday = today.weekday()  # Mon=0 ... Sun=6

    # Tuesday = 1
    days_to_tuesday = (1 - weekday) % 7
    expiry = today + timedelta(days=days_to_tuesday)

    # If today is Tuesday after 3:30 PM → next week's expiry
    if weekday == 1 and today.hour >= 15:
        expiry += timedelta(days=7)

    return expiry.strftime("%d-%b-%Y")
