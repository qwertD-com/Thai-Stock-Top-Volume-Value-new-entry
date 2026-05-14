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

def force_sync(sh, name, data):
    df = pd.DataFrame(data)
    try:
        ws = sh.worksheet(name)
        ws.clear()
    except:
        ws = sh.add_worksheet(title=name, rows='100', cols='20')
    ws.update([df.columns.values.tolist()] + df.values.tolist(), 'A1')
    print(f'Synced {name} with {len(df)} rows.')

def main():
    print(f'Update started at {datetime.now()}')

    # 1. Load Tickers
    df_set = pd.read_html(MASTER_FILE, header=1)[0]
    tickers = [str(s).strip() + '.BK' for s in df_set['Symbol'] if str(s).strip() and str(s) != 'nan']

    # 2. Fetch Data (40-day window to ensure 15 trading days)
    end = datetime.now() + timedelta(days=1)
    start = end - timedelta(days=40)
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
                        stats.append({'Ticker': t, 'Vol': v, 'Price': c, 'Metric': m})
            except: continue
        return pd.DataFrame(stats).sort_values('Metric', ascending=False).head(20) if not pd.DataFrame(stats).empty else pd.DataFrame()

    # 4. Build Persistence Pools
    hist_vol_pool = set()
    hist_val_pool = set()
    for d in hist_dates:
        v_top = get_top_20(d, 'volume')
        if not v_top.empty: hist_vol_pool.update(v_top['Ticker'].tolist())
        a_top = get_top_20(d, 'value')
        if not a_top.empty: hist_val_pool.update(a_top['Ticker'].tolist())

    # 5. Build Reports
    vol_raw = get_top_20(today, 'volume')
    vol_final = [{'Date': today_str, 'Rank': i+1, 'Ticker': r['Ticker'], 'Volume': int(r['Vol']),
                  'Value_MB': round((r['Vol']*r['Price'])/1e6, 2), 
                  'Status': 'NEW ENTRY' if r['Ticker'] not in hist_vol_pool else ''}
                 for i, r in vol_raw.reset_index().iterrows()]

    val_raw = get_top_20(today, 'value')
    val_final = [{'Date': today_str, 'Rank': i+1, 'Ticker': r['Ticker'], 'Price': r['Price'],
                  'Value_MB': round(r['Metric']/1e6, 2), 
                  'Status': 'NEW ENTRY' if r['Ticker'] not in hist_val_pool else ''}
                 for i, r in val_raw.reset_index().iterrows()]

    # 6. Sync to Google Sheets
    gc = get_gspread_client()
    sh = gc.open(SHEET_NAME)
    force_sync(sh, 'Volume Ranking', vol_final)
    force_sync(sh, 'Value Analysis', val_final)
    print(f'✅ Successfully synced: {today_str}')

if __name__ == '__main__':
    main()
