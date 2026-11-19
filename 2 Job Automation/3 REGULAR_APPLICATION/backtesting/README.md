# Gold (XAUUSD) 3-Minute Tokyo Opening Range Breakout (ORB) Strategy Backtesting Engine

This folder contains the complete, reproducible backtesting suite and quantitative audit for the **Gold (XAUUSD) 3-Minute Tokyo Opening Range Breakout (ORB) Strategy** with **ADX Filter** and **1:2 Risk-to-Reward Ratio**.

---

## 1. Strategy Parameters & Rules

- **Instrument:** Gold (`XAUUSD` / `TVC:GOLD`).
- **Timeframe:** **3-Minute (`3m`)**.
- **Session Anchor:** **05:30 AM IST (00:00 UTC / 09:00 AM JST)** (Tokyo Market Opening).
- **Opening Range:** First 3-minute candle (00:00:00 to 00:03:00 UTC). Range High ($H_{range}$) and Range Low ($L_{range}$).
- **Momentum Filter:** Wilder's **$\text{ADX}(14) > 20$** required at breakout close.
- **Entry:**
  - **Long:** Candle closes above $H_{range}$ with $ADX > 20$.
  - **Short:** Candle closes below $L_{range}$ with $ADX > 20$.
- **Stop Loss:**
  - Long: $L_{range} - \text{buffer}$ (default buffer = $0.50).
  - Short: $H_{range} + \text{buffer}$ (default buffer = $0.50).
- **Take Profit:** Strictly **1:2 R:R** ($TP = \text{Entry} \pm 2 \times \text{Risk}$).
- **Daily Limits:** Max **2 trades per day**.
  - **Scenario A:** Trade 1 wins (+2R) $\rightarrow$ Stop for the day.
  - **Scenario B:** Trade 1 loses (-1R), Trade 2 wins (+2R) $\rightarrow$ Net day = +1R.
  - **Scenario C:** Trade 1 loses (-1R), Trade 2 loses (-1R) $\rightarrow$ Net day = -2R.
  - **Scenario D:** Trade 1 loses (-1R), no Trade 2 triggered $\rightarrow$ Net day = -1R.

---

## 2. Directory Architecture

```
backtesting/
│
├── data_repo/                      # Cloned from https://github.com/ravalmeet/TradingView-Data
│   └── TradingviewData/            # TradingView WebSocket data client
│
├── data_loader.py                  # Ingestion pipeline for TradingView (TVC:GOLD) & historical parquet
├── orb_strategy.py                 # Core ORB strategy engine, ADX(14) computation & metric tracking
├── main.py                         # Single unified backtest CLI runner & chart generator
│
├── tvc_gold_3m.parquet             # TradingView TVC:GOLD 3m dataset (5,945 bars)
├── xauusd_3m_2022.parquet          # High-frequency 3m gold data for 2022 (118,212 bars)
├── xauusd_3m_2023.parquet          # High-frequency 3m gold data for 2023 (102,986 bars)
├── xauusd_3m_2024.parquet          # High-frequency 3m gold data for 2024 (118,554 bars)
│
├── orb_trades_2022_2024.csv        # Detailed trade logs (1,246 executions with timestamps, entries, exits)
├── orb_daily_2022_2024.csv         # Session-by-session scenario performance log (771 trading days)
└── orb_complete_report_charts.png  # 4-panel publication-grade quantitative performance visualization
```

---

## 3. How to Reproduce the Backtest

To run the complete audit, sensitivity sweeps, log generation, and visual charting:

```bash
cd backtesting
python main.py
```

---

## 4. Summary of Empirical Findings

| Metric | Video Claim | Empirical Reality (2022–2024) | TradingView TVC:GOLD (Oct 2026) |
| :--- | :--- | :--- | :--- |
| **Win Rate** | **75.00%+** | **31.78% (1,246 trades)** | **31.58% (19 trades)** |
| **Random Walk 1:2 Boundary** | 33.33% | 33.33% | 33.33% |
| **Net Return (Spread = $0.25)** | Large Profit | **-130.85 R** | **-1.38 R** |
| **Frictionless Return ($0 spread)** | Large Profit | **+28.15 R (PF: 1.03)** | **+0.12 R** |
| **Spread Drag** | Ignored | **-159.00 R lost to spread** | **-1.50 R lost to spread** |
| **Max Consecutive Losses** | 2 | **14 consecutive** | **7 consecutive** |
| **Max Drawdown** | Minimal | **-144.59 R** | **-7.23 R** |
| **Martingale Lot Scaling** | "Systematic recovery"| **-167.76 R (-193.54 R Max DD)** | Accelerated Drawdown |

**Conclusion:** The claimed 75% win rate is unfeasible for a 1:2 R:R system on 3-minute Tokyo Gold. The strategy exhibits an empirical win rate of ~31.8% (random-walk baseline) and is severely degraded by broker spread friction.
