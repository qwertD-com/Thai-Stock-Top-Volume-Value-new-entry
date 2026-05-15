import os
import json
import time
import pandas as pd
import yfinance as yf
import gspread
from datetime import datetime, timedelta
from collections import Counter
from google.oauth2.service_account import Credentials

# --- CONFIGURATION ---
SHEET_NAME = 'Thai Stock Daily Report'
MASTER_FILE = 'listedCompanies_en_US.xls'

# Add new IPO tickers here (e.g., ['NEWSTOCK.BK'])
MANUAL_IPO_TICKERS = []

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
    if not data_list: return
    try:
        ws = sh.worksheet(name)
        ws.clear()
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=name, rows='100', cols='10')
    ws.update([headers] + data_list, 'A1')
    print(f'✅ Worksheet {name} updated.')

def main():
    print(f'🚀 Update started at {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')

    if not os.path.exists(MASTER_FILE):
        print(f'❌ Error: {MASTER_FILE} not found.')
        return

    # 1. Parse Tickers
    try:
        df_list = pd.read_html(MASTER_FILE, header=1)
        df_set = df_list[0]
        official_tickers = [str(s).strip() + '.BK' for s in df_set['Symbol'] if str(s).strip() and str(s).lower() != 'nan']
        tickers = list(set(official_tickers + MANUAL_IPO_TICKERS))
        print(f'✅ Loaded {len(tickers)} tickers ({len(MANUAL_IPO_TICKERS)} manual).')
    except Exception as e:
        print(f'❌ Parse Error: {e}'); return

    # 2. Fetch Data (45-day window)
    end = datetime.now() + timedelta(days=1)
    start = end - timedelta(days=45)
    data = yf.download(tickers, start=start, end=end, group_by='ticker', progress=False, auto_adjust=True)

    dates = pd.Index(sorted(data.index.unique()))
    if dates.empty:
        print('❌ Error: No market data fetched.'); return

    today = dates[-1]
    today_str = today.strftime('%Y-%m-%d')
    hist_dates = dates[max(0, dates.get_loc(today)-15) : dates.get_loc(today)]

    def get_top_20(target_date, mode='volume'):
        stats = []
        for t in tickers:
            try:
                if t not in data.columns.levels[0]: continue
                t_df = data[t]
                if target_date in t_df.index:
                    v = float(t_df.loc[target_date, 'Volume'])
                    h, l, c = float(t_df.loc[target_date, 'High']), float(t_df.loc[target_date, 'Low']), float(t_df.loc[target_date, 'Close'])
                    typical_p = (h + l + c) / 3
                    if v > 0 and not pd.isna(c):
                        metric = v if mode == 'volume' else v * typical_p
                        stats.append({'Ticker': t, 'Metric': metric, 'Price': round(c, 2), 'Vol': int(v)})
            except:
                continue
        if not stats: return pd.DataFrame(columns=['Ticker', 'Metric', 'Price', 'Vol'])
        return pd.DataFrame(stats).sort_values('Metric', ascending=False).head(20)

    # 3. Persistence Analysis
    print('⌛ Analyzing persistence...')
    hist_vol_counts = Counter()
    hist_val_counts = Counter()
    for d in hist_dates:
        hist_vol_counts.update(get_top_20(d, 'volume')['Ticker'].tolist())
        hist_val_counts.update(get_top_20(d, 'value')['Ticker'].tolist())

    headers = ['Date', 'Rank', 'Ticker', 'Price', 'Volume', 'Value_MB', 'Days_in_Top_20_15D', 'Status']

    # 4. Sync to Sheets ( RENAMED TABS: Volume and Values )
    try:
        gc = get_gspread_client()
        sh = gc.open(SHEET_NAME)

        for name, mode, counter in [('Volume', 'volume', hist_vol_counts), ('Values', 'value', hist_val_counts)]:
            raw_top = get_top_20(today, mode)
            report_data = []
            for i, (_, r) in enumerate(raw_top.iterrows(), 1):
                count = counter.get(r['Ticker'], 0)
                report_data.append([
                    today_str, i, r['Ticker'], r['Price'], r['Vol'],
                    round(r['Metric'] / 1e6, 2),
                    count, 'NEW ENTRY' if count == 0 else ''
                ])
            force_update_sheet(sh, name, report_data, headers)
            time.sleep(1)

        print(f'✅ SUCCESS! Updated for {today_str}.')
    except Exception as e:
        print(f'❌ Sync failed: {e}')

if __name__ == '__main__':
    main()
