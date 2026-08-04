import psxdata
import gspread
from google.oauth2.service_account import Credentials
import requests
import time
import os
import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo
import os
import sys

PAKISTAN_TZ = ZoneInfo("Asia/Karachi")

now = datetime.now(PAKISTAN_TZ)

MANUAL_RUN = os.environ.get("MANUAL_RUN") == "1"

if now.weekday() == 4:  # Friday
    MARKET_OPEN = datetime.strptime("09:30", "%H:%M").time()
    MARKET_CLOSE = datetime.strptime("16:00", "%H:%M").time()
else:
    MARKET_OPEN = datetime.strptime("09:30", "%H:%M").time()
    MARKET_CLOSE = datetime.strptime("15:30", "%H:%M").time()

market_open = (
    now.weekday() < 5
    and MARKET_OPEN <= now.time() <= MARKET_CLOSE
)

if not market_open and not MANUAL_RUN:
    if now.weekday() >= 5:
        print("PSX CLOSED - Weekend")
    else:
        print("PSX CLOSED - Outside market hours")

    print("Automatic run - nothing to update.")
    sys.exit(0)

if MANUAL_RUN:
    print("MANUAL RUN - proceeding even though PSX may be closed.")
else:
    print("PSX OPEN")

print("Pakistan time:", now.strftime("%Y-%m-%d %H:%M:%S"))
# ============================================================
# SETTINGS
# ============================================================

SPREADSHEET_ID = "1t575nYx7UN-8k9ird0bwrKtIUkzcFD8N5FMDVG0Lx6k"

WORKSHEET_NAME = "Stock Market"

SERVICE_ACCOUNT_FILE = "service_account.json"

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

spreadsheet = client.open_by_key(SPREADSHEET_ID)

sheet = spreadsheet.worksheet(WORKSHEET_NAME)


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

        data = result.get("data", [])

        if not data:

            print(
                symbol,
                "Current: no data"
            )

            return None

        # PSX returns newest trade first
        latest_trade = data[0]

        # [timestamp, price, volume]
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

tickers = sheet.get(TICKER_RANGE)


# ============================================================
# READ EXISTING VALUES
#
# IMPORTANT:
# If a fetch fails, we keep the old value.
# ============================================================

old_ldcp = sheet.get(LDCP_RANGE)

old_current = sheet.get(CURRENT_RANGE)


# ============================================================
# PREPARE RESULTS
# ============================================================

ldcp_results = []

current_results = []


# ============================================================
# PROCESS EACH STOCK
# ============================================================

for i, row in enumerate(tickers):

    symbol = row[0].strip().upper() if row and row[0] else ""

    # Existing values
    existing_ldcp = (
        old_ldcp[i][0]
        if i < len(old_ldcp) and old_ldcp[i]
        else ""
    )

    existing_current = (
        old_current[i][0]
        if i < len(old_current) and old_current[i]
        else ""
    )

    if not symbol:

        ldcp_results.append([existing_ldcp])
        current_results.append([existing_current])

        continue

    print("")
    print("========================================")
    print("Processing:", symbol)
    print("========================================")

    # --------------------------------------------------------
    # LDCP
    # --------------------------------------------------------

    ldcp = get_previous_close(symbol)

    if ldcp is None:

        # Keep old value
        ldcp_results.append([existing_ldcp])

        print(
            symbol,
            "LDCP fetch failed - keeping:",
            existing_ldcp
        )

    else:

        ldcp_results.append([ldcp])

    # --------------------------------------------------------
    # CURRENT PRICE
    # --------------------------------------------------------

    current = get_current_price(symbol)

    if current is None:

        # Keep old value
        current_results.append([existing_current])

        print(
            symbol,
            "Current fetch failed - keeping:",
            existing_current
        )

    else:

        current_results.append([current])

    # Small delay
    time.sleep(0.2)


# ============================================================
# UPDATE ONLY F3:F15
# ============================================================

sheet.update(
    range_name=LDCP_RANGE,
    values=ldcp_results
)


# ============================================================
# UPDATE ONLY G3:G15
# ============================================================

sheet.update(
    range_name=CURRENT_RANGE,
    values=current_results
)
from datetime import datetime
from zoneinfo import ZoneInfo


update_date = now.strftime("%d-%m-%Y")
update_time = now.strftime("%I:%M:%S %p")

sheet.update(
    range_name="T2",
    values=[[f"{update_date}\n{update_time}"]]
)

# ============================================================
# DONE
# ============================================================

print("")
print("========================================")
print("UPDATE COMPLETE")
print("========================================")
print("F3:F15 = Previous trading-day close")
print("G3:G15 = Current/latest PSX trade")
print("")
print("Failed fetches kept their previous values.")
print("B3:B15 was NOT changed.")
print("All other cells were NOT changed.")
print("========================================")
