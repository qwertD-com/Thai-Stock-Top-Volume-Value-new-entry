# --- FINAL PRODUCTION SCRIPT (main.py) ---
import os
import json
import pandas as pd
import yfinance as yf
import gspread
from datetime import datetime, timedelta
from google.oauth2.service_account import Credentials

# --- CONFIGURATION ---
SHEET_NAME = 'Thai Stock Daily Report'
MASTER_FILE = 'listedCompanies_en_US.xls'

def get_gspread_client():
    creds_json = os.getenv('GOOGLE_SHEETS_CREDENTIALS')
    if creds_json:
        # GitHub Actions Mode
        info = json.loads(creds_json)
        creds = Credentials.from_service_account_info(
            info, scopes=['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        )
        return gspread.authorize(creds)
    else:
        # Local/Colab Testing Mode
        from google.colab import auth, default
        auth.authenticate_user()
        creds, _ = default()
        return gspread.authorize(creds)

def main():
    print(f"Update started at {datetime.now()}")

    # 1. Load Tickers
    if not os.path.exists(MASTER_FILE):
        print(f"Error: {MASTER_FILE} not found in root directory.")
        return

    df_set = pd.read_html(MASTER_FILE, header=1)[0]
    all_thai_tickers = [str(symbol).strip() + '.BK' for symbol in df_set['Symbol'] if str(symbol).strip() and str(symbol) != 'nan']

    # 2. Fetch Market Data
    end_date = datetime.now() + timedelta(days=1)
    start_date = end_date - timedelta(days=45)
    print(f"Downloading data for {len(all_thai_tickers)} tickers...")
    data_raw = yf.download(all_thai_tickers, start=start_date, end=end_date, group_by='ticker', progress=False, auto_adjust=True)

    # 3. Analyze Dates
    available_dates = pd.Index(sorted(data_raw.index.unique()))
    if available_dates.empty:
        print("No market data found.")
        return

    today = available_dates[-1]
    idx = available_dates.get_loc(today)
    # The last 15 trading days before today
    historical_window = available_dates[max(0, idx-15) : idx]
    print(f"Processing Data for Session: {today.strftime('%Y-%m-%d')}")

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
        if not stats:
            return pd.DataFrame(columns=['Ticker', 'Metric', 'Price', 'Vol'])
        return pd.DataFrame(stats).sort_values(by='Metric', ascending=False).head(20)

    # 4. Build Historical Persistence Pool
    hist_pool = set()
    for d in historical_window:
        df_h = get_top_20(d, 'volume')
        if not df_h.empty:
            hist_pool.update(df_h['Ticker'].tolist())

    # 5. Generate Reports
    # Volume Report
    vol_df = get_top_20(today, 'volume')
    vol_report = []
    for i, (_, row) in enumerate(vol_df.iterrows(), 1):
        vol_report.append({
            'Rank': i, 'Ticker': row['Ticker'], 'Volume': row['Vol'],
            'Value_MB': round((row['Vol']*row['Price'])/1e6, 2),
            'Status': 'NEW ENTRY' if row['Ticker'] not in hist_pool else ''
        })

    # Value Report
    val_df = get_top_20(today, 'value')
    val_report = [{'Rank': i, 'Ticker': r['Ticker'], 'Price': r['Price'], 'Value_MB': round(r['Metric']/1e6, 2)}
                  for i, (_, r) in enumerate(val_df.iterrows(), 1)]

    # 6. Sync to Google Sheets
    try:
        gc = get_gspread_client()
        sh = gc.open(SHEET_NAME)

        for name, data in [('Volume Ranking', vol_report), ('Value Analysis', val_report)]:
            if not data: continue
            df = pd.DataFrame(data)
            try: ws = sh.worksheet(name)
            except: ws = sh.add_worksheet(title=name, rows='100', cols='10')
            ws.clear()
            ws.update([df.columns.values.tolist()] + df.values.tolist(), 'A1')

        print(f"✅ Successfully synced: {today.strftime('%Y-%m-%d')}")
    except Exception as e:
        print(f"❌ Sync failed: {e}")

if __name__ == '__main__':
    main()
