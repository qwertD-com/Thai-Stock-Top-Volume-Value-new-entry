import os
import json
import pandas as pd
import yfinance as yf
import gspread
from datetime import datetime, timedelta
from collections import Counter
from google.oauth2.service_account import Credentials

# --- CONFIGURATION ---
SHEET_NAME = 'Thai Stock Daily Report'
MASTER_FILE = 'listedCompanies_en_US.xls'

def get_gspread_client():
    # 1. Check for GitHub Actions Environment Variable
    creds_json = os.getenv('GOOGLE_SHEETS_CREDENTIALS')
    if creds_json:
        info = json.loads(creds_json)
        creds = Credentials.from_service_account_info(
            info, scopes=['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        )
        return gspread.authorize(creds)
    else:
        # 2. Fallback to Google Colab Authentication
        from google.colab import auth
        from google.auth import default
        auth.authenticate_user()
        creds, _ = default()
        return gspread.authorize(creds)

def main():
    print(f"Update started at {datetime.now()}")

    # 1. Load Tickers
    if not os.path.exists(MASTER_FILE):
        print(f"Error: {MASTER_FILE} not found.")
        return

    df_set = pd.read_html(MASTER_FILE, header=1)[0]
    all_thai_tickers = [str(symbol).strip() + '.BK' for symbol in df_set['Symbol'] if str(symbol).strip() and str(symbol) != 'nan']

    # 2. Fetch Market Data (Last 45 days ensures we have 15 trading days)
    end_date = datetime.now() + timedelta(days=1)
    start_date = end_date - timedelta(days=45)
    data_raw = yf.download(all_thai_tickers, start=start_date, end=end_date, group_by='ticker', progress=False, auto_adjust=True)

    # 3. Analyze Dates
    available_dates = pd.Index(sorted(data_raw.index.unique()))
    today = available_dates[-1]
    today_str = today.strftime('%Y-%m-%d')
    idx = available_dates.get_loc(today)
    historical_window = available_dates[max(0, idx-15) : idx]

    def get_top_20(target_date, mode='volume'):
        stats = []
        for t in all_thai_tickers:
            try:
                ticker_df = data_raw[t]
                if target_date in ticker_df.index:
                    vol = float(ticker_df.loc[target_date, 'Volume'])
                    close = float(ticker_df.loc[target_date, 'Close'])
                    if vol > 0:
                        metric = vol if mode == 'volume' else vol * close
                        stats.append({'Ticker': t, 'Metric': metric, 'Price': round(close, 2), 'Vol': int(vol)})
            except: continue
        if not stats: return pd.DataFrame(columns=['Ticker', 'Metric', 'Price', 'Vol'])
        return pd.DataFrame(stats).sort_values(by='Metric', ascending=False).head(20)

    # 4. Build Historical Persistence Pools
    hist_vol_pool = set()
    hist_val_pool = set()
    for d in historical_window:
        hist_vol_pool.update(get_top_20(d, 'volume')['Ticker'].tolist())
        hist_val_pool.update(get_top_20(d, 'value')['Ticker'].tolist())

    # 5. Build Reports
    # Volume Report
    vol_df = get_top_20(today, 'volume')
    vol_data = []
    for i, (_, row) in enumerate(vol_df.iterrows(), 1):
        vol_data.append([
            today_str, row['Ticker'], row['Price'], row['Vol'],
            round((row['Vol']*row['Price'])/1e6, 2), 'YES' if row['Ticker'] not in hist_vol_pool else 'NO'
        ])

    # Value Report
    val_df = get_top_20(today, 'value')
    val_data = []
    for i, (_, row) in enumerate(val_df.iterrows(), 1):
        val_data.append([
            today_str, row['Ticker'], row['Price'], row['Vol'],
            round(row['Metric']/1e6, 2), 'YES' if row['Ticker'] not in hist_val_pool else 'NO'
        ])

    # 6. Sync to Google Sheets
    HEADERS = ['Date', 'Ticker', 'Price', 'Volume', 'Value_MB', 'New Entry']
    try:
        gc = get_gspread_client()
        sh = gc.open(SHEET_NAME)
        for name, data in [('Volume Ranking', vol_data), ('Value Analysis', val_data)]:
            try: ws = sh.worksheet(name)
            except: ws = sh.add_worksheet(title=name, rows='100', cols='10')
            ws.clear()
            ws.update([HEADERS] + data, 'A1')
        print(f"✅ Successfully synced: {today_str}")
    except Exception as e: 
        print(f"❃ Sync failed: {e}")

if __name__ == '__main__':
    main()
