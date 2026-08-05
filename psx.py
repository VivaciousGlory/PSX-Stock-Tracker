import psxdata
import gspread
from google.oauth2.service_account import Credentials
import requests
import time
import os
import json
import sys

from datetime import datetime, time as datetime_time
from zoneinfo import ZoneInfo


# ============================================================
# TIMEZONE
# ============================================================

PAKISTAN_TZ = ZoneInfo("Asia/Karachi")

now = datetime.now(PAKISTAN_TZ)

MANUAL_RUN = os.environ.get("MANUAL_RUN") == "1"


# ============================================================
# PSX MARKET HOURS
# ============================================================

# Monday - Thursday
# 09:30 AM - 03:30 PM PKT

# Friday
# 09:30 AM - 04:00 PM PKT

if now.weekday() == 4:
    # Friday
    MARKET_OPEN = datetime_time(9, 30)
    MARKET_CLOSE = datetime_time(16, 0)
else:
    # Monday - Thursday
    MARKET_OPEN = datetime_time(9, 30)
    MARKET_CLOSE = datetime_time(15, 30)


# ============================================================
# FINAL CHECK WINDOW
# ============================================================

# The final GitHub Actions check is scheduled around:
#
# 16:07 PKT
#
# Allow automatic updates until 16:15 PKT.

FINAL_CHECK_END = datetime_time(16, 15)


# ============================================================
# DETERMINE CURRENT RUN
# ============================================================

is_weekday = now.weekday() < 5

market_open = (
    is_weekday
    and MARKET_OPEN <= now.time() <= MARKET_CLOSE
)

final_check = (
    is_weekday
    and MARKET_CLOSE < now.time() <= FINAL_CHECK_END
)


# ============================================================
# RUN DECISION
# ============================================================

if MANUAL_RUN:

    print("========================================")
    print("MANUAL RUN")
    print("========================================")
    print("Proceeding regardless of market hours.")
    print("")

elif market_open:

    print("========================================")
    print("PSX OPEN")
    print("========================================")
    print("Normal market update.")
    print("")

elif final_check:

    print("========================================")
    print("PSX FINAL CHECK")
    print("========================================")
    print("Market is closed.")
    print("Running final price check.")
    print("")

else:

    print("========================================")

    if now.weekday() >= 5:
        print("PSX CLOSED - WEEKEND")
    else:
        print("PSX CLOSED - OUTSIDE MARKET HOURS")

    print("========================================")
    print("Automatic run - nothing to update.")
    print("")

    sys.exit(0)


print(
    "Pakistan time:",
    now.strftime("%Y-%m-%d %H:%M:%S")
)

print("")


# ============================================================
# SETTINGS
# ============================================================

SPREADSHEET_ID = "1t575nYx7UN-8k9ird0bwrKtIUkzcFD8N5FMDVG0Lx6k"

WORKSHEET_NAME = "Stock Market"

TICKER_RANGE = "B4:B16"

LDCP_RANGE = "F4:F16"

CURRENT_RANGE = "G4:G16"


# ============================================================
# GOOGLE SHEETS CONNECTION
# ============================================================

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

service_account_info = json.loads(
    os.environ["GOOGLE_SERVICE_ACCOUNT"]
)

credentials = Credentials.from_service_account_info(
    service_account_info,
    scopes=SCOPES
)

client = gspread.authorize(credentials)

spreadsheet = client.open_by_key(
    SPREADSHEET_ID
)

sheet = spreadsheet.worksheet(
    WORKSHEET_NAME
)


# ============================================================
# PSX REQUEST SETTINGS
# ============================================================

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://dps.psx.com.pk/"
}


# ============================================================
# GET CURRENT PRICE
# ============================================================

def get_current_price(symbol):

    try:

        url = f"https://dps.psx.com.pk/timeseries/int/{symbol}"

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=15
        )

        if response.status_code != 200:

            print(
                symbol,
                "Current HTTP:",
                response.status_code
            )

            return None

        result = response.json()

        data = result.get(
            "data",
            []
        )

        if not data:

            print(
                symbol,
                "Current: no data"
            )

            return None

        # PSX returns newest trade first.
        # [timestamp, price, volume]

        latest_trade = data[0]

        current_price = latest_trade[1]

        print(
            symbol,
            "CURRENT:",
            current_price
        )

        return float(current_price)

    except Exception as e:

        print(
            symbol,
            "CURRENT FAILED:",
            e
        )

        return None


# ============================================================
# GET PREVIOUS TRADING DAY CLOSE
# ============================================================

def get_previous_close(symbol):

    try:

        data = psxdata.stocks(symbol)

        if data is None or data.empty:

            print(
                symbol,
                "LDCP: no historical data"
            )

            return None

        # Newest trading day first

        data = data.sort_values(
            "date",
            ascending=False
        ).reset_index(drop=True)

        if len(data) < 2:

            print(
                symbol,
                "LDCP: not enough data"
            )

            return None

        latest_date = data.iloc[0]["date"]

        latest_close = data.iloc[0]["close"]

        previous_date = data.iloc[1]["date"]

        previous_close = data.iloc[1]["close"]

        print(
            symbol,
            "LDCP:",
            previous_date,
            "=",
            previous_close
        )

        return float(previous_close)

    except Exception as e:

        print(
            symbol,
            "LDCP FAILED:",
            e
        )

        return None


# ============================================================
# READ TICKERS
# ============================================================

tickers = sheet.get(
    TICKER_RANGE
)


# ============================================================
# READ EXISTING VALUES
#
# If a fetch fails, the old value is kept.
# ============================================================

old_ldcp = sheet.get(
    LDCP_RANGE
)

old_current = sheet.get(
    CURRENT_RANGE
)


# ============================================================
# PREPARE RESULTS
# ============================================================

ldcp_results = []

current_results = []


# ============================================================
# PROCESS EACH STOCK
# ============================================================

for i, row in enumerate(tickers):

    symbol = (
        row[0].strip().upper()
        if row and row[0]
        else ""
    )

    # Existing LDCP

    existing_ldcp = (
        old_ldcp[i][0]
        if i < len(old_ldcp)
        and old_ldcp[i]
        else ""
    )

    # Existing current price

    existing_current = (
        old_current[i][0]
        if i < len(old_current)
        and old_current[i]
        else ""
    )

    # Empty symbol

    if not symbol:

        ldcp_results.append(
            [existing_ldcp]
        )

        current_results.append(
            [existing_current]
        )

        continue

    print("")
    print("========================================")
    print("Processing:", symbol)
    print("========================================")

    # ========================================================
    # LDCP
    # ========================================================

    ldcp = get_previous_close(
        symbol
    )

    if ldcp is None:

        # Keep old value

        ldcp_results.append(
            [existing_ldcp]
        )

        print(
            symbol,
            "LDCP fetch failed - keeping:",
            existing_ldcp
        )

    else:

        ldcp_results.append(
            [ldcp]
        )

    # ========================================================
    # CURRENT PRICE
    # ========================================================

    current = get_current_price(
        symbol
    )

    if current is None:

        # Keep old value

        current_results.append(
            [existing_current]
        )

        print(
            symbol,
            "Current fetch failed - keeping:",
            existing_current
        )

    else:

        current_results.append(
            [current]
        )

    # Small delay

    time.sleep(0.2)


# ============================================================
# UPDATE LDCP
# F4:F16
# ============================================================

sheet.update(
    range_name=LDCP_RANGE,
    values=ldcp_results
)


# ============================================================
# UPDATE CURRENT PRICE
# G4:G16
# ============================================================

sheet.update(
    range_name=CURRENT_RANGE,
    values=current_results
)


# ============================================================
# UPDATE LAST UPDATE TIME
# T2
# ============================================================

update_date = now.strftime(
    "%d-%m-%Y"
)

update_time = now.strftime(
    "%I:%M:%S %p"
)

sheet.update(
    range_name="T2",
    values=[
        [
            f"{update_date}\n{update_time}"
        ]
    ]
)


# ============================================================
# DONE
# ============================================================

print("")
print("========================================")
print("UPDATE COMPLETE")
print("========================================")

print(
    "F4:F16 = Previous trading-day close"
)

print(
    "G4:G16 = Current/latest PSX trade"
)

print(
    "T2 = Last update time"
)

print("")

print(
    "Failed fetches kept their previous values."
)

print(
    "B4:B16 was NOT changed."
)

print(
    "All other cells were NOT changed."
)

print("========================================")
