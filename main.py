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

def force_update_sheet(sh, name, data_list, headers):
    if not data_list:
        return
    try:
        ws = sh.worksheet(name)
        ws.clear()
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=name, rows='100', cols='20')
    
    # Standardized update with headers and data
    ws.update([headers] + data_list, 'A1')
    print(f'✅ Worksheet {name} updated.')

def main():
    print(f'Update started at {datetime.now()}')

    # 1. Load Tickers
    if not os.path.exists(MASTER_FILE):
        print(f'Error: {MASTER_FILE} not found.')
        return

    df_set = pd.read_html(MASTER_FILE, header=1)[0]
    tickers = [str(s).strip() + '.BK' for s in df_set['Symbol'] if str(s).strip() and str(s) != 'nan']

    # 2. Fetch Market Data (45 days ensures we have 15 trading days)
    end = datetime.now() + timedelta(days=1)
    start = end - timedelta(days=45)
    data = yf.download(tickers, start=start, end=end, group_by='ticker', progress=False, auto_adjust=True)

    # 3. Analyze Dates
    dates = pd.Index(sorted(data.index.unique()))
    today = dates[-1]
    today_str = today.strftime('%Y-%m-%d')
    hist_dates = dates[max(0, dates.get_loc(today)-15) : dates.get_loc(today)]

    def get_top_20(target_date, mode='volume'):
        stats = []
        for t in tickers:
            try:
                t_df = data[t]
                if target_date in t_df.index:
                    v, c = float(t_df.loc[target_date, 'Volume']), float(t_df.loc[target_date, 'Close'])
                    if v > 0:
                        m = v if mode == 'volume' else v * c
                        stats.append({'Ticker': t, 'Metric': m, 'Price': round(c, 2), 'Vol': int(v)})
            except: continue
        if not stats: return pd.DataFrame(columns=['Ticker', 'Metric', 'Price', 'Vol'])
        return pd.DataFrame(stats).sort_values('Metric', ascending=False).head(20)

    # 4. Build Historical Persistence Pools
    hist_vol_pool = set()
    hist_val_pool = set()
    for d in hist_dates:
        hist_vol_pool.update(get_top_20(d, 'volume')['Ticker'].tolist())
        hist_val_pool.update(get_top_20(d, 'value')['Ticker'].tolist())

    # 5. Build Reports
    # Columns: Date, Rank, Ticker, Price, Volume, Value_MB, Status
    headers = ['Date', 'Rank', 'Ticker', 'Price', 'Volume', 'Value_MB', 'Status']

    # Volume Report
    vol_raw = get_top_20(today, 'volume')
    vol_data = []
    for i, (_, r) in enumerate(vol_raw.iterrows(), 1):
        vol_data.append([
            today_str, i, r['Ticker'], r['Price'], r['Vol'],
            round((r['Vol']*r['Price'])/1e6, 2), 
            'NEW ENTRY' if r['Ticker'] not in hist_vol_pool else ''
        ])

    # Value Report
    val_raw = get_top_20(today, 'value')
    val_data = []
    for i, (_, r) in enumerate(val_raw.iterrows(), 1):
        val_data.append([
            today_str, i, r['Ticker'], r['Price'], r['Vol'],
            round(r['Metric']/1e6, 2), 
            'NEW ENTRY' if r['Ticker'] not in hist_val_pool else ''
        ])

    # 6. Sync to Google Sheets
    try:
        gc = get_gspread_client()
        sh = gc.open(SHEET_NAME)
        force_update_sheet(sh, 'Volume Ranking', vol_data, headers)
        force_update_sheet(sh, 'Value Analysis', val_data, headers)
        print(f'✅ Successfully synced for {today_str}.')
    except Exception as e:
        print(f'❌ Sync failed: {e}')

if __name__ == '__main__':
    main()
