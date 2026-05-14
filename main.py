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

def main():
    print(f"Update started at {datetime.now()}")
    
    # 1. Load Tickers
    df_set = pd.read_html(MASTER_FILE, header=1)[0]
    all_thai_tickers = [str(symbol).strip() + '.BK' for symbol in df_set['Symbol'] if str(symbol).strip()]

    # 2. Fetch Market Data
    end_date = datetime.now()
    start_date = end_date - timedelta(days=40)
    data_raw = yf.download(all_thai_tickers, start=start_date, end=end_date, group_by='ticker', progress=False, auto_adjust=True)

    # 3. Analyze Dates
    available_dates = pd.Index(sorted(data_raw.index.unique()))
    today = available_dates[-1]
    historical_window = available_dates[max(0, available_dates.get_loc(today)-15) : available_dates.get_loc(today)]

    def get_top_20(d, mode='volume'):
        stats = []
        for t in all_thai_tickers:
            try:
                ticker_df = data_raw[t]
                if d in ticker_df.index:
                    vol = float(ticker_df.loc[d, 'Volume'])
                    close = float(ticker_df.loc[d, 'Close'])
                    if vol > 0:
                        metric = vol if mode == 'volume' else vol * close
                        stats.append({'Ticker': t, 'Metric': metric, 'Price': round(close, 2), 'Vol': int(vol)})
            except: continue
        return pd.DataFrame(stats).sort_values(by='Metric', ascending=False).head(20) if stats else pd.DataFrame()

    # 4. Process Persistence
    hist_pool = set()
    for d in historical_window:
        hist_pool.update(get_top_20(d, 'volume')['Ticker'].tolist())

    # 5. Build Reports
    vol_df = get_top_20(today, 'volume')
    vol_report = []
    for i, (_, row) in enumerate(vol_df.iterrows(), 1):
        vol_report.append({
            'Rank': i, 'Ticker': row['Ticker'], 'Volume': row['Vol'], 
            'Value_MB': round((row['Vol']*row['Price'])/1e6, 2), 
            'Status': 'NEW ENTRY' if row['Ticker'] not in hist_pool else ''
        })

    val_df = get_top_20(today, 'value')
    val_report = [{'Rank': i, 'Ticker': r['Ticker'], 'Price': r['Price'], 'Value_MB': round(r['Metric']/1e6, 2)} 
                  for i, (_, r) in enumerate(val_df.iterrows(), 1)]

    # 6. Sync to Google Sheets
    gc = get_gspread_client()
    sh = gc.open(SHEET_NAME)
    
    for name, data in [('Volume Ranking', vol_report), ('Value Analysis', val_report)]:
        df = pd.DataFrame(data)
        try: ws = sh.worksheet(name)
        except: ws = sh.add_worksheet(title=name, rows='100', cols='10')
        ws.clear()
        ws.update([df.columns.values.tolist()] + df.values.tolist(), 'A1')

    print(f"Successfully synced: {today.strftime('%Y-%m-%d')}")

if __name__ == '__main__':
    main()
