import os
import sys
import shutil
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from data_loader import get_tradingview_gold_data, get_multiyear_gold_data
from orb_strategy import backtest_tokyo_orb, calculate_metrics, compute_adx

def run_all_backtests():
    print("=" * 80, flush=True)
    print(" GOLD (XAUUSD) 3-MINUTE TOKYO OPENING RANGE BREAKOUT (ORB) STRATEGY AUDIT", flush=True)
    print("=" * 80, flush=True)
    
    # 1. TradingView Data Run
    print("\n[Step 1] Loading TradingView Data (TVC:GOLD 3m)...", flush=True)
    df_tv = get_tradingview_gold_data()
    df_tv['ADX'] = compute_adx(df_tv)
    
    t_tv, d_tv = backtest_tokyo_orb(df_tv, adx_threshold=20.0, buffer=0.5, spread=0.25, max_entry_hour=6)
    m_tv = calculate_metrics(t_tv, d_tv)
    
    print(f"TradingView TVC:GOLD Results (Tokyo Window):", flush=True)
    print(f"  Trades: {m_tv.get('total_trades')}, Wins: {m_tv.get('win_count')}, Losses: {m_tv.get('loss_count')}")
    print(f"  Win Rate: {m_tv.get('win_rate', 0):.2f}% (Claimed: 75.00%)")
    print(f"  Total Net Return: {m_tv.get('total_r', 0):.2f} R, Profit Factor: {m_tv.get('profit_factor', 0):.2f}")
    
    # 2. Multi-Year Archive Run
    print("\n[Step 2] Loading Multi-Year Gold Intraday Archive (2022-2024)...", flush=True)
    dfs = get_multiyear_gold_data()
    for k in ["2022", "2023", "2024"]:
        if k in dfs:
            dfs[k]['ADX'] = compute_adx(dfs[k])
            
    df_comb = dfs.get("Combined (2022-2024)")
    if df_comb is not None:
        df_comb['ADX'] = compute_adx(df_comb)
        
    multiyear_results = {}
    print("\n--- Annual & Multi-Year Baseline Results (Spread = $0.25, ADX > 20, Buffer = $0.5) ---", flush=True)
    for k in ["2022", "2023", "2024", "Combined (2022-2024)"]:
        if k in dfs:
            t, d = backtest_tokyo_orb(dfs[k], adx_threshold=20.0, buffer=0.5, spread=0.25, max_entry_hour=6, scaling=False)
            m = calculate_metrics(t, d)
            multiyear_results[k] = (m, t, d)
            print(f"[{k}] Trades: {m.get('total_trades')}, Win Rate: {m.get('win_rate', 0):.2f}%, Total R: {m.get('total_r', 0):.2f}R, PF: {m.get('profit_factor', 0):.2f}, Max DD: {m.get('max_dd_r', 0):.2f}R, Sharpe: {m.get('sharpe_ratio', 0):.2f}", flush=True)
            print(f"   Scenarios: {m.get('scenarios')}", flush=True)

    # 3. Frictionless vs Real Spread
    print("\n[Step 3] Comparing Frictionless vs Spread Drag...", flush=True)
    t_fric, d_fric = backtest_tokyo_orb(df_comb, adx_threshold=20.0, buffer=0.5, spread=0.0, max_entry_hour=6)
    m_fric = calculate_metrics(t_fric, d_fric)
    print(f"Frictionless (Spread $0.00): Trades: {m_fric.get('total_trades')}, Win Rate: {m_fric.get('win_rate', 0):.2f}%, Return: {m_fric.get('total_r', 0):.2f}R, PF: {m_fric.get('profit_factor', 0):.2f}", flush=True)
    
    # 4. Lot Scaling (Martingale)
    print("\n[Step 4] Auditing Positive Lot Scaling (2x on Trade 2)...", flush=True)
    t_scale, d_scale = backtest_tokyo_orb(df_comb, adx_threshold=20.0, buffer=0.5, spread=0.25, max_entry_hour=6, scaling=True)
    m_scale = calculate_metrics(t_scale, d_scale)
    print(f"Lot Scaling (Martingale): Trades: {m_scale.get('total_trades')}, Win Rate: {m_scale.get('win_rate', 0):.2f}%, Return: {m_scale.get('total_r', 0):.2f}R, Max DD: {m_scale.get('max_dd_r', 0):.2f}R", flush=True)

    # 5. Sensitivity Sweeps
    print("\n[Step 5] Running Parameter Sensitivity Sweeps...", flush=True)
    adx_sweep = {}
    for th in [np.nan, 15.0, 20.0, 25.0, 30.0]:
        t_adx, d_adx = backtest_tokyo_orb(df_comb, adx_threshold=th, buffer=0.5, spread=0.25, max_entry_hour=6)
        m_adx = calculate_metrics(t_adx, d_adx)
        name = "No ADX" if np.isnan(th) else f"ADX>{int(th)}"
        adx_sweep[name] = m_adx
        print(f"  [{name}] Win Rate: {m_adx.get('win_rate', 0):.2f}%, Return: {m_adx.get('total_r', 0):.2f}R, PF: {m_adx.get('profit_factor', 0):.2f}", flush=True)
        
    buff_sweep = {}
    for b in [0.0, 0.5, 1.0, 2.0]:
        t_b, d_b = backtest_tokyo_orb(df_comb, adx_threshold=20.0, buffer=b, spread=0.25, max_entry_hour=6)
        m_b = calculate_metrics(t_b, d_b)
        name = f"Buffer ${b:.1f}"
        buff_sweep[name] = m_b
        print(f"  [{name}] Win Rate: {m_b.get('win_rate', 0):.2f}%, Return: {m_b.get('total_r', 0):.2f}R, PF: {m_b.get('profit_factor', 0):.2f}", flush=True)

    # 6. Save Data Logs
    _, t_base, d_base = multiyear_results["Combined (2022-2024)"]
    trades_csv = os.path.join(current_dir, "orb_trades_2022_2024.csv")
    daily_csv = os.path.join(current_dir, "orb_daily_2022_2024.csv")
    t_base.to_csv(trades_csv, index=False)
    d_base.to_csv(daily_csv, index=False)
    print(f"\n[Step 6] Saved trade logs to {trades_csv} and daily logs to {daily_csv}.", flush=True)

    # 7. Generate 4-Panel Visualization
    print("\n[Step 7] Generating Publication-Quality 4-Panel Visualization...", flush=True)
    fig, axes = plt.subplots(2, 2, figsize=(16, 11))
    fig.suptitle("Gold (XAUUSD) 3-Minute Tokyo ORB Strategy - Quantitative Backtest Audit", fontsize=16, fontweight='bold', y=0.98)

    # Panel A: Equity Curves
    ax1 = axes[0, 0]
    t_base_copy = t_base.copy()
    t_base_copy['cum_r'] = t_base_copy['r_pnl'].cumsum()
    ax1.plot(t_base_copy['entry_time'], t_base_copy['cum_r'], label=f"Baseline (ADX>20, WinRate {multiyear_results['Combined (2022-2024)'][0]['win_rate']:.1f}%, Net {t_base_copy['r_pnl'].sum():.1f}R)", color="#1f77b4", linewidth=1.8)
    
    t_fric_copy = t_fric.copy()
    t_fric_copy['cum_r'] = t_fric_copy['r_pnl'].cumsum()
    ax1.plot(t_fric_copy['entry_time'], t_fric_copy['cum_r'], label=f"Zero Friction (Spread $0.0, Net {t_fric['r_pnl'].sum():.1f}R)", color="#2ca02c", linestyle="--", linewidth=1.5)
    
    t_scale_copy = t_scale.copy()
    t_scale_copy['cum_r'] = t_scale_copy['r_pnl'].cumsum()
    ax1.plot(t_scale_copy['entry_time'], t_scale_copy['cum_r'], label=f"Lot Scaling (2x on T2, Net {t_scale['r_pnl'].sum():.1f}R)", color="#d62728", linestyle=":", linewidth=1.6)

    ax1.axhline(0, color='black', linestyle='-', alpha=0.3)
    ax1.set_title("A. Cumulative Performance Over 3 Years (2022-2024)", fontsize=12, fontweight='bold')
    ax1.set_ylabel("Cumulative Profit (R-multiples)", fontsize=11)
    ax1.legend(loc="lower left", frameon=True)
    ax1.grid(True, linestyle="--", alpha=0.5)

    # Panel B: Win Rate vs Claimed 75%
    ax2 = axes[0, 1]
    cats = ['TV Oct 2026', '2022', '2023', '2024', '3-Yr Comb.', 'Random Walk (1:2)', 'Claimed Rate']
    rates = [m_tv.get('win_rate', 0), multiyear_results['2022'][0]['win_rate'], multiyear_results['2023'][0]['win_rate'], multiyear_results['2024'][0]['win_rate'], multiyear_results['Combined (2022-2024)'][0]['win_rate'], 33.33, 75.00]
    colors = ['#4a90e2', '#357abd', '#2a5d8f', '#1d4263', '#e67e22', '#7f8c8d', '#e74c3c']

    bars = ax2.bar(cats, rates, color=colors, width=0.55, edgecolor='black', linewidth=0.8)
    ax2.axhline(33.33, color='#7f8c8d', linestyle='--', linewidth=1.2, label='1:2 Breakeven / Random Walk (33.3%)')
    ax2.axhline(75.00, color='#e74c3c', linestyle=':', linewidth=1.5, label='Claimed Win Rate (75.0%)')
    ax2.set_ylim(0, 85)
    ax2.set_title("B. Win Rate Comparison: Empirical Reality vs. Claimed 75%", fontsize=12, fontweight='bold')
    ax2.set_ylabel("Win Rate (%)", fontsize=11)
    for bar in bars:
        yval = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width()/2.0, yval + 1.5, f"{yval:.1f}%", ha='center', va='bottom', fontsize=10, fontweight='bold')
    ax2.legend(loc="upper left", frameon=True)
    ax2.grid(True, linestyle="--", alpha=0.5, axis='y')

    # Panel C: Daily Scenario Distribution
    ax3 = axes[1, 0]
    scen_dict = multiyear_results['Combined (2022-2024)'][0]['scenarios']
    scen_labels = ['Scenario A\n(Won T1: +2R)', 'Scenario B\n(Lost T1, Won T2: +1R)', 'Scenario C\n(Lost Both: -2R)', 'Loss T1, No T2\n(-1R)']
    scen_counts = [scen_dict.get('SCENARIO_A', 0), scen_dict.get('SCENARIO_B', 0), scen_dict.get('SCENARIO_C', 0), scen_dict.get('LOSS_NO_T2', 0)]
    scen_colors = ['#2ecc71', '#3498db', '#e74c3c', '#e67e22']
    wedges, texts, autotexts = ax3.pie(scen_counts, labels=scen_labels, autopct='%1.1f%%', startangle=140, colors=scen_colors, explode=(0.03, 0.03, 0.05, 0.03), wedgeprops=dict(edgecolor='black', linewidth=0.8))
    for at in autotexts:
        at.set_fontweight('bold')
    ax3.set_title("C. Daily Outcome Distribution (771 Active Trading Days)", fontsize=12, fontweight='bold')

    # Panel D: Sensitivity Analysis
    ax4 = axes[1, 1]
    param_names = list(adx_sweep.keys()) + list(buff_sweep.keys())
    net_vals = [m['total_r'] for m in adx_sweep.values()] + [m['total_r'] for m in buff_sweep.values()]
    bar_cols = ['#c0392b' if x < -100 else '#d35400' if x < -50 else '#f39c12' for x in net_vals]
    bars4 = ax4.bar(param_names, net_vals, color=bar_cols, width=0.55, edgecolor='black', linewidth=0.8)
    ax4.axhline(0, color='black', linestyle='-', alpha=0.5)
    ax4.set_title("D. Sensitivity Analysis: Net Return (R) Across Parameters", fontsize=12, fontweight='bold')
    ax4.set_ylabel("Total Profit / Loss (R-Multiples)", fontsize=11)
    for bar in bars4:
        yval = bar.get_height()
        va = 'top' if yval < 0 else 'bottom'
        offset = -6 if yval < 0 else 3
        ax4.text(bar.get_x() + bar.get_width()/2.0, yval + offset, f"{yval:.0f}R", ha='center', va=va, fontsize=9, fontweight='bold')
    ax4.grid(True, linestyle="--", alpha=0.5, axis='y')

    plt.tight_layout()
    chart_file = os.path.join(current_dir, "orb_complete_report_charts.png")
    plt.savefig(chart_file, dpi=200)
    plt.close()
    print(f"Chart saved to {chart_file}.", flush=True)

    # Copy chart to artifact directory
    artifact_chart = r"C:\Users\raval\.gemini\antigravity\brain\735d2ef5-73a0-4821-b873-98defc181798\orb_complete_report_charts.png"
    shutil.copy(chart_file, artifact_chart)
    print(f"Copied visualization to artifact directory: {artifact_chart}", flush=True)

    print("\n" + "=" * 80, flush=True)
    print(" AUDIT COMPLETE: ALL CODE & ARTIFACTS CONSOLIDATED IN 'backtesting/'", flush=True)
    print("=" * 80, flush=True)

if __name__ == "__main__":
    run_all_backtests()
