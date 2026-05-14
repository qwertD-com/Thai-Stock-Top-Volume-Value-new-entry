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
    creds_json = os.getenv('GOOGLE_SHEETS_CREDENTIALS')
    if creds_json:
        info = json.loads(creds_json)
        creds = Credentials.from_service_account_info(
            info, scopes=['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        )
        return gspread.authorize(creds)
    else:
        from google.colab import auth, default
        auth.authenticate_user()
        creds, _ = default()
        return gspread.authorize(creds)

def force_update_sheet(sh, name, data_list, headers):
    if not data_list:
        print(f'Skipping {name}: No data.')
        return
    try:
        ws = sh.worksheet(name)
        ws.clear()
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=name, rows='100', cols='20')

    ws.update([headers] + data_list, 'A1')
    print(f"✅ Worksheet '{name}' updated with {len(data_list)} rows.")

def main():
    print(f'Update started at {datetime.now()}')

    if not os.path.exists(MASTER_FILE):
        print(f"Error: {MASTER_FILE} not found.")
        return

    df_set = pd.read_html(MASTER_FILE, header=1)[0]
    all_thai_tickers = [str(symbol).strip() + '.BK' for symbol in df_set['Symbol'] if str(symbol).strip() and str(symbol) != 'nan']

    # 2. Fetch Market Data (45 days to guarantee 15 trading days)
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

    # 4. Build Historical Persistence Maps
    hist_vol_counts = Counter()
    hist_val_counts = Counter()

    for d in historical_window:
        v_top = get_top_20(d, 'volume')
        if not v_top.empty: hist_vol_counts.update(v_top['Ticker'].tolist())
        a_top = get_top_20(d, 'value')
        if not a_top.empty: hist_val_counts.update(a_top['Ticker'].tolist())

    # 5. Build Reports following Columns A-G
    headers = ['Date', 'Ticker', 'Price', 'Volume', 'Values_MB', 'Days_in_Top_20_Prev_15D', 'Status']

    # Volume Report
    vol_df = get_top_20(today, 'volume')
    vol_data = []
    for _, r in vol_df.iterrows():
        count = hist_vol_counts.get(r['Ticker'], 0)
        vol_data.append([
            today_str, r['Ticker'], r['Price'], r['Vol'],
            round((r['Vol']*r['Price'])/1e6, 2), count,
            'YES' if count == 0 else 'NO'
        ])

    # Value Report
    val_df = get_top_20(today, 'value')
    val_data = []
    for _, r in val_df.iterrows():
        count = hist_val_counts.get(r['Ticker'], 0)
        val_data.append([
            today_str, r['Ticker'], r['Price'], r['Vol'],
            round(r['Metric']/1e6, 2), count,
            'YES' if count == 0 else 'NO'
        ])

    # 6. Sync to Google Sheets
    try:
        gc = get_gspread_client()
        sh = gc.open(SHEET_NAME)
        force_update_sheet(sh, 'Volume Ranking', vol_data, headers)
        force_update_sheet(sh, 'Value Analysis', val_data, headers)
        print(f"🚀 Successfully synced: {today_str}")
    except Exception as e:
        print(f"❌ Sync failed: {e}")

if __name__ == '__main__':
    main()
