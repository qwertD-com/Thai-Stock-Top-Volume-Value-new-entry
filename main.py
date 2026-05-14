import os
import json
import pandas as pd
import yfinance as yf
import gspread
from datetime import datetime, timedelta
from collections import Counter
from google.oauth2.service_account import Credentials
import time

# --- CONFIGURATION ---
SHEET_NAME = 'Thai Stock Daily Report'
MASTER_FILE = 'listedCompanies_en_US.xls'

def get_gspread_client():
    creds_json = os.getenv('GOOGLE_SHEETS_CREDENTIALS')
    if creds_json:
        info = json.loads(creds_json)
        creds = Credentials.from_service_account_info(
            info, scopes=['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        )
        return gspread.authorize(creds)
    else:
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

    ws.update([headers] + data_list, 'A1')
    print(f'✅ Worksheet {name} updated.')

def main():
    print(f'Update started at {datetime.now()}')

    if not os.path.exists(MASTER_FILE):
        print(f'Error: {MASTER_FILE} not found.')
        return

    df_set = pd.read_html(MASTER_FILE, header=1)[0]
    tickers = [str(s).strip() + '.BK' for s in df_set['Symbol'] if str(s).strip() and str(s) != 'nan']

    # Fetch 45 days to ensure 15 trading days coverage
    end = datetime.now() + timedelta(days=1)
    start = end - timedelta(days=45)
    data = yf.download(tickers, start=start, end=end, group_by='ticker', progress=False, auto_adjust=True)

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
                    vol = float(t_df.loc[target_date, 'Volume'])
                    close = float(t_df.loc[target_date, 'Close'])
                    if vol > 0:
                        metric = vol if mode == 'volume' else vol * close
                        stats.append({'Ticker': t, 'Metric': metric, 'Price': round(close, 2), 'Vol': int(vol)})
            except: continue
        if not stats: return pd.DataFrame(columns=['Ticker', 'Metric', 'Price', 'Vol'])
        return pd.DataFrame(stats).sort_values('Metric', ascending=False).head(20)

    hist_vol_counts = Counter()
    hist_val_counts = Counter()
    for d in hist_dates:
        hist_vol_counts.update(get_top_20(d, 'volume')['Ticker'].tolist())
        hist_val_counts.update(get_top_20(d, 'value')['Ticker'].tolist())

    # Final Headers as requested
    headers = ['Date', 'Rank', 'Ticker', 'Price', 'Volume', 'Value_MB', 'Days_in_Top_20_15D', 'Status']

    # Volume Report
    vol_raw = get_top_20(today, 'volume')
    vol_data = []
    for i, (_, r) in enumerate(vol_raw.iterrows(), 1):
        count = hist_vol_counts.get(r['Ticker'], 0)
        vol_data.append([
            today_str, i, r['Ticker'], r['Price'], r['Vol'], 
            round((r['Vol']*r['Price'])/1e6, 2), 
            count, 
            'NEW ENTRY' if count == 0 else ''
        ])

    # Value Report
    val_raw = get_top_20(today, 'value')
    val_data = []
    for i, (_, r) in enumerate(val_raw.iterrows(), 1):
        count = hist_val_counts.get(r['Ticker'], 0)
        val_data.append([
            today_str, i, r['Ticker'], r['Price'], r['Vol'], 
            round(r['Metric']/1e6, 2), 
            count, 
            'NEW ENTRY' if count == 0 else ''
        ])

    try:
        gc = get_gspread_client()
        sh = gc.open(SHEET_NAME)
        force_update_sheet(sh, 'Volume Ranking', vol_data, headers)
        time.sleep(2)
        force_update_sheet(sh, 'Value Analysis', val_data, headers)
        print(f'✅ Successfully synced for {today_str}.')
    except Exception as e:
        print(f'❌ Sync failed: {e}')

if __name__ == '__main__':
    main()
