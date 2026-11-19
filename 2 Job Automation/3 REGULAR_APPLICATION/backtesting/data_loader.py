import os
import sys
import datetime
import pandas as pd

# Add data_repo to sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
data_repo_path = os.path.join(current_dir, "data_repo")
if data_repo_path not in sys.path:
    sys.path.insert(0, data_repo_path)

from TradingviewData import TradingViewData, Interval

def get_tradingview_gold_data(n_bars=5944, cache_file="tvc_gold_3m.parquet", force_download=False):
    """
    Downloads or loads cached 3-minute Gold data from TradingView (TVC:GOLD).
    Uses the TradingViewData library from the requested GitHub repository.
    """
    cache_path = os.path.join(current_dir, cache_file)
    if os.path.exists(cache_path) and not force_download:
        print(f"[DataLoader] Loading cached TradingView data from {cache_file}...", flush=True)
        df = pd.read_parquet(cache_path)
        return df

    print(f"[DataLoader] Connecting to TradingView WebSocket for TVC:GOLD (n_bars={n_bars})...", flush=True)
    tv = TradingViewData()
    # TVC uses GOLD ticker for spot gold index
    df = tv.get_hist(symbol="GOLD", exchange="TVC", interval=Interval.min_3, n_bars=n_bars)
    if df is not None and not df.empty:
        # Convert index to UTC timezone
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        else:
            df.index = df.index.tz_convert("UTC")
        df.index.name = "datetime_utc"
        df.sort_index(inplace=True)
        df.to_parquet(cache_path)
        print(f"[DataLoader] Successfully fetched and cached {len(df)} bars to {cache_file}.", flush=True)
        return df
    else:
        raise ValueError("Failed to retrieve data from TradingView.")

def get_multiyear_gold_data():
    """
    Loads 2022, 2023, 2024 3-minute Gold data.
    """
    files = {
        "2022": os.path.join(current_dir, "xauusd_3m_2022.parquet"),
        "2023": os.path.join(current_dir, "xauusd_3m_2023.parquet"),
        "2024": os.path.join(current_dir, "xauusd_3m_2024.parquet")
    }
    dfs = {}
    for y, path in files.items():
        if os.path.exists(path):
            df = pd.read_parquet(path)
            dfs[y] = df
        else:
            print(f"[DataLoader] Warning: {path} not found.")
            
    if dfs:
        dfs["Combined (2022-2024)"] = pd.concat(list(dfs.values())).sort_index()
    return dfs

if __name__ == "__main__":
    df_tv = get_tradingview_gold_data()
    print("TradingView data shape:", df_tv.shape)
    dfs_my = get_multiyear_gold_data()
    for k, v in dfs_my.items():
        print(f"Multi-year {k} shape:", v.shape)
