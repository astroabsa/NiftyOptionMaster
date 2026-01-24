from datetime import datetime, timedelta

def get_next_weekly_expiry():
    today = datetime.now()
    weekday = today.weekday()  # Mon=0 ... Sun=6

    days_to_thursday = (3 - weekday) % 7
    expiry = today + timedelta(days=days_to_thursday)

    # If today is Thursday and after 3:30 PM → take next week
    if weekday == 3 and today.hour >= 15:
        expiry += timedelta(days=7)

    return expiry.strftime("%d-%b-%Y")
