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

if now.weekday() == 4:
    MARKET_OPEN = datetime_time(9, 10)
    MARKET_CLOSE = datetime_time(16, 30)
    FINAL_CHECK_END = datetime_time(16, 40)
else:
    MARKET_OPEN = datetime_time(9, 30)
    MARKET_CLOSE = datetime_time(15, 30)
    FINAL_CHECK_END = datetime_time(15, 40)


current_time = now.replace(second=0, microsecond=0).time()

is_weekday = now.weekday() < 5

market_open = (
    is_weekday
    and MARKET_OPEN <= current_time <= MARKET_CLOSE
)

final_check = (
    is_weekday
    and MARKET_CLOSE < current_time <= FINAL_CHECK_END
)

if MANUAL_RUN:

    print("========================================")
    print("MANUAL RUN")
    print("========================================")
    print("Proceeding regardless of market hours.\n")

elif market_open:

    print("========================================")
    print("PSX OPEN")
    print("========================================")
    print("Normal market update.\n")

elif final_check:

    print("========================================")
    print("PSX FINAL CHECK")
    print("========================================")
    print("Running final price check.\n")

else:

    print("========================================")

    if now.weekday() >= 5:
        print("PSX CLOSED - WEEKEND")
    else:
        print("PSX CLOSED - OUTSIDE MARKET HOURS")

    print("========================================")
    print("Automatic run - nothing to update.\n")

    sys.exit(0)

print("Pakistan time:", now.strftime("%Y-%m-%d %H:%M:%S"))
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

MAX_RETRIES = 5


def connect_sheet():

    for attempt in range(MAX_RETRIES):

        try:

            spreadsheet = client.open_by_key(
                SPREADSHEET_ID
            )

            worksheet = spreadsheet.worksheet(
                WORKSHEET_NAME
            )

            print("Connected to Google Sheets.\n")

            return worksheet

        except Exception as e:

            print(
                f"Connection failed ({attempt+1}/{MAX_RETRIES})"
            )

            print(e)

            if attempt == MAX_RETRIES - 1:
                raise

            time.sleep(10)


sheet = connect_sheet()


# ============================================================
# RETRY HELPERS
# ============================================================

def sheet_get(range_name):

    for attempt in range(MAX_RETRIES):

        try:

            return sheet.get(range_name)

        except Exception as e:

            print(
                f"GET {range_name} failed ({attempt+1}/{MAX_RETRIES})"
            )

            print(e)

            if attempt == MAX_RETRIES - 1:
                raise

            time.sleep(10)


def sheet_update(range_name, values):

    for attempt in range(MAX_RETRIES):

        try:

            sheet.update(
                range_name=range_name,
                values=values
            )

            return

        except Exception as e:

            print(
                f"UPDATE {range_name} failed ({attempt+1}/{MAX_RETRIES})"
            )

            print(e)

            if attempt == MAX_RETRIES - 1:
                raise

            time.sleep(10)


# ============================================================
# PSX REQUEST SETTINGS
# ============================================================

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://dps.psx.com.pk/"
}



# ============================================================
# GET CURRENT PRICE - PSX MARKET WATCH
# ============================================================

def get_current_price(symbol):

    try:

        url = "https://dps.psx.com.pk/market-watch"

        response = requests.get(
            url,
            headers={
                **HEADERS,
                "X-Requested-With": "XMLHttpRequest"
            },
            timeout=20
        )

        response.raise_for_status()

        from bs4 import BeautifulSoup

        soup = BeautifulSoup(response.text, "html.parser")

        # Find the market-watch table containing the requested symbol.
        for table in soup.find_all("table"):

            headers = [
                cell.get_text(" ", strip=True).upper()
                for cell in table.find_all("th")
            ]

            if not headers:
                continue

            symbol_index = next(
                (
                    i for i, name in enumerate(headers)
                    if name in ("SYMBOL", "SCRIP", "COMPANY")
                ),
                None
            )

            current_index = next(
                (
                    i for i, name in enumerate(headers)
                    if name in ("CURRENT", "PRICE", "CLOSE")
                ),
                None
            )

            if symbol_index is None or current_index is None:
                continue

            for tr in table.find_all("tr"):

                cells = tr.find_all(["td", "th"])

                if len(cells) <= max(symbol_index, current_index):
                    continue

                row_symbol = cells[symbol_index].get_text(
                    " ", strip=True
                ).upper()

                if row_symbol != symbol:
                    continue

                # Prefer machine-readable numeric values when available.
                cell = cells[current_index]

                raw_price = (
                    cell.get("data-order")
                    or cell.get("data-value")
                    or cell.get_text(" ", strip=True)
                )

                current_price = float(
                    str(raw_price).replace(",", "").strip()
                )

                if current_price <= 0:
                    return None

                print(symbol, "CURRENT:", current_price)

                return current_price

        print(symbol, "CURRENT: symbol/price column not found")
        return None

    except Exception as e:

        print(symbol, "CURRENT FAILED:", e)

        return None

# ============================================================
# GET PREVIOUS CLOSE
# ============================================================

def get_previous_close(symbol):

    try:

        data = psxdata.stocks(symbol)

        if data is None or data.empty:

            print(symbol, "LDCP: no data")

            return None

        data = data.sort_values(
            "date",
            ascending=False
        ).reset_index(drop=True)

        if len(data) < 2:

            print(symbol, "LDCP: not enough data")

            return None

        previous_close = data.iloc[1]["close"]

        previous_date = data.iloc[1]["date"]

        print(symbol, "LDCP:", previous_date, "=", previous_close)

        return float(previous_close)

    except Exception as e:

        print(symbol, "LDCP FAILED:", e)

        return None


# ============================================================
# READ TICKERS
# ============================================================

tickers = sheet_get(TICKER_RANGE)

# ============================================================
# READ EXISTING VALUES
# ============================================================

old_ldcp = sheet_get(LDCP_RANGE)

old_current = sheet_get(CURRENT_RANGE)

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

    ldcp = get_previous_close(symbol)

    if ldcp is None:

        ldcp_results.append([existing_ldcp])

        print(
            symbol,
            "LDCP fetch failed - keeping:",
            existing_ldcp
        )

    else:

        ldcp_results.append([ldcp])

    current = get_current_price(symbol)

    if current is None:

        current_results.append([existing_current])

        print(
            symbol,
            "Current fetch failed - keeping:",
            existing_current
        )

    else:

        current_results.append([current])

    time.sleep(0.2)

# ============================================================
# UPDATE GOOGLE SHEET
# ============================================================

sheet_update(
    LDCP_RANGE,
    ldcp_results
)

sheet_update(
    CURRENT_RANGE,
    current_results
)

# Recompute current PKT timestamp at completion time
now = datetime.now(PAKISTAN_TZ)
update_date = now.strftime("%d-%m-%Y")
update_time = now.strftime("%I:%M:%S %p")

sheet_update(
    "T2",
    [[f"{update_date}\n{update_time}"]]
)

# ============================================================
# DONE
# ============================================================

print("")
print("========================================")
print("UPDATE COMPLETE")
print("========================================")
print("F4:F16 = Previous trading-day close")
print("G4:G16 = Current/latest PSX trade")
print("T2 = Last update time")
print("")
print("Failed fetches kept their previous values.")
print("B4:B16 was NOT changed.")
print("All other cells were NOT changed.")
print("========================================")
