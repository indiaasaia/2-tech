import numpy as np
import pandas as pd

def compute_adx(df, period=14):
    """
    Computes Wilder's ADX for a DataFrame containing 'high', 'low', 'close'.
    Uses standard Wilder smoothing with alpha = 1 / period.
    """
    high = df['high'].values
    low = df['low'].values
    close = df['close'].values
    n = len(df)
    
    tr = np.zeros(n)
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        hl = high[i] - low[i]
        h_pc = abs(high[i] - close[i - 1])
        l_pc = abs(low[i] - close[i - 1])
        tr[i] = max(hl, h_pc, l_pc)
        
        up_move = high[i] - high[i - 1]
        down_move = low[i - 1] - low[i]
        
        if up_move > down_move and up_move > 0:
            plus_dm[i] = up_move
        else:
            plus_dm[i] = 0.0
            
        if down_move > up_move and down_move > 0:
            minus_dm[i] = down_move
        else:
            minus_dm[i] = 0.0
            
    atr = np.zeros(n)
    smooth_plus_dm = np.zeros(n)
    smooth_minus_dm = np.zeros(n)
    
    if n < period * 2:
        return pd.Series(np.nan, index=df.index)
        
    atr[period] = np.mean(tr[1:period+1])
    smooth_plus_dm[period] = np.mean(plus_dm[1:period+1])
    smooth_minus_dm[period] = np.mean(minus_dm[1:period+1])
    
    for i in range(period + 1, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
        smooth_plus_dm[i] = (smooth_plus_dm[i - 1] * (period - 1) + plus_dm[i]) / period
        smooth_minus_dm[i] = (smooth_minus_dm[i - 1] * (period - 1) + minus_dm[i]) / period
        
    plus_di = np.zeros(n)
    minus_di = np.zeros(n)
    dx = np.zeros(n)
    
    for i in range(period, n):
        if atr[i] > 0:
            plus_di[i] = 100.0 * (smooth_plus_dm[i] / atr[i])
            minus_di[i] = 100.0 * (smooth_minus_dm[i] / atr[i])
        sum_di = plus_di[i] + minus_di[i]
        if sum_di > 0:
            dx[i] = 100.0 * (abs(plus_di[i] - minus_di[i]) / sum_di)
            
    adx = np.full(n, np.nan)
    start_adx = 2 * period
    if n > start_adx:
        adx[start_adx] = np.mean(dx[period+1:start_adx+1])
        for i in range(start_adx + 1, n):
            adx[i] = (adx[i - 1] * (period - 1) + dx[i]) / period
            
    return pd.Series(adx, index=df.index, name="ADX")


def backtest_tokyo_orb(df, adx_threshold=20.0, buffer=0.5, spread=0.25, max_entry_hour=6, force_eod_close=True, scaling=False):
    """
    Backtests the Gold (XAUUSD) 3-Minute Tokyo Opening Range Breakout Strategy.
    
    Parameters:
    -----------
    df : pd.DataFrame
        DataFrame with datetime index (UTC), columns ['open', 'high', 'low', 'close', 'ADX'].
    adx_threshold : float
        Minimum ADX required for breakout confirmation (default 20.0, np.nan for no filter).
    buffer : float
        Distance in points beyond range boundary to place Stop Loss (default $0.50).
    spread : float
        Bid-ask spread + slippage per round-trip trade (default $0.25).
    max_entry_hour : int
        Maximum UTC hour to accept new trade signals (default 6:00 UTC = 11:30 AM IST = Tokyo session).
    force_eod_close : bool
        Whether to close open positions at the end of the trading session.
    scaling : bool
        If True, applies 2x lot scaling (Martingale) on Trade 2 following a loss on Trade 1.
    """
    df = df.copy()
    if 'ADX' not in df.columns:
        df['ADX'] = compute_adx(df)
        
    df['date'] = df.index.date
    trades = []
    daily_summaries = []
    
    grouped = df.groupby('date', sort=False)
    
    for d, day_df in grouped:
        # Tokyo market open candle at 05:30 AM IST = 00:00:00 UTC
        open_candles = day_df[day_df.index.strftime('%H:%M') == '00:00']
        if open_candles.empty:
            daily_summaries.append({'date': d, 'scenario': 'NO_ORB_CANDLE', 'day_r': 0.0, 'trades': 0})
            continue
            
        orb_candle = open_candles.iloc[0]
        orb_high = orb_candle['high']
        orb_low = orb_candle['low']
        orb_time = open_candles.index[0]
        
        if orb_high <= orb_low:
            continue
            
        subsequent = day_df[day_df.index > orb_time]
        if subsequent.empty:
            daily_summaries.append({'date': d, 'scenario': 'NO_DATA_AFTER_ORB', 'day_r': 0.0, 'trades': 0})
            continue
            
        daily_trades = []
        active_trade = None
        
        for idx, row in subsequent.iterrows():
            current_time = idx
            h, l, c = row['high'], row['low'], row['close']
            adx_val = row['ADX']
            
            # 1. Manage Active Position
            if active_trade is not None:
                direction = active_trade['direction']
                tp = active_trade['tp']
                sl = active_trade['sl']
                
                exit_price = None
                exit_reason = None
                
                if direction == 'LONG':
                    hit_sl = (l <= sl)
                    hit_tp = (h >= tp)
                    if hit_sl and hit_tp:
                        exit_price = sl - (spread / 2.0)
                        exit_reason = 'SL_AMBIG'
                    elif hit_sl:
                        exit_price = sl - (spread / 2.0)
                        exit_reason = 'SL'
                    elif hit_tp:
                        exit_price = tp - (spread / 2.0)
                        exit_reason = 'TP'
                else: # SHORT
                    hit_sl = (h >= sl)
                    hit_tp = (l <= tp)
                    if hit_sl and hit_tp:
                        exit_price = sl + (spread / 2.0)
                        exit_reason = 'SL_AMBIG'
                    elif hit_sl:
                        exit_price = sl + (spread / 2.0)
                        exit_reason = 'SL'
                    elif hit_tp:
                        exit_price = tp + (spread / 2.0)
                        exit_reason = 'TP'
                        
                if exit_price is not None:
                    active_trade['exit_time'] = current_time
                    active_trade['exit_price'] = exit_price
                    active_trade['exit_reason'] = exit_reason
                    
                    if direction == 'LONG':
                        pnl_pts = exit_price - active_trade['entry_price']
                    else:
                        pnl_pts = active_trade['entry_price'] - exit_price
                        
                    raw_r = pnl_pts / active_trade['risk']
                    active_trade['pnl_pts'] = pnl_pts
                    active_trade['r_pnl'] = raw_r * active_trade['lot_mult']
                    trades.append(active_trade)
                    daily_trades.append(active_trade)
                    
                    # Scenario A: Win on trade 1 -> Stop trading for the day immediately!
                    if exit_reason == 'TP' and len(daily_trades) == 1:
                        active_trade = None
                        break
                        
                    active_trade = None
                    # Max 2 trades per day limit
                    if len(daily_trades) >= 2:
                        break
                        
                elif force_eod_close and idx == subsequent.index[-1]:
                    # Force session close
                    exit_price = c
                    exit_reason = 'EOD'
                    if direction == 'LONG':
                        pnl_pts = exit_price - active_trade['entry_price']
                    else:
                        pnl_pts = active_trade['entry_price'] - exit_price
                    raw_r = pnl_pts / active_trade['risk']
                    active_trade['exit_time'] = current_time
                    active_trade['exit_price'] = exit_price
                    active_trade['exit_reason'] = exit_reason
                    active_trade['pnl_pts'] = pnl_pts
                    active_trade['r_pnl'] = raw_r * active_trade['lot_mult']
                    trades.append(active_trade)
                    daily_trades.append(active_trade)
                    active_trade = None
                    break
                    
            # 2. Check for New Breakout Signal
            if active_trade is None and len(daily_trades) < 2:
                if current_time.hour > max_entry_hour:
                    continue
                    
                long_signal = (c > orb_high) and (np.isnan(adx_threshold) or adx_val > adx_threshold)
                short_signal = (c < orb_low) and (np.isnan(adx_threshold) or adx_val > adx_threshold)
                
                trade_idx = len(daily_trades) + 1
                lot_mult = 2.0 if (scaling and trade_idx == 2) else 1.0
                
                if long_signal and not short_signal:
                    entry_price = c + (spread / 2.0)
                    sl = orb_low - buffer
                    risk = entry_price - sl
                    if risk > 0:
                        tp = entry_price + (2.0 * risk)
                        active_trade = {
                            'date': d,
                            'trade_num': trade_idx,
                            'direction': 'LONG',
                            'orb_high': orb_high,
                            'orb_low': orb_low,
                            'entry_time': current_time,
                            'entry_price': entry_price,
                            'sl': sl,
                            'tp': tp,
                            'risk': risk,
                            'adx_at_entry': adx_val,
                            'lot_mult': lot_mult
                        }
                elif short_signal and not long_signal:
                    entry_price = c - (spread / 2.0)
                    sl = orb_high + buffer
                    risk = sl - entry_price
                    if risk > 0:
                        tp = entry_price - (2.0 * risk)
                        active_trade = {
                            'date': d,
                            'trade_num': trade_idx,
                            'direction': 'SHORT',
                            'orb_high': orb_high,
                            'orb_low': orb_low,
                            'entry_time': current_time,
                            'entry_price': entry_price,
                            'sl': sl,
                            'tp': tp,
                            'risk': risk,
                            'adx_at_entry': adx_val,
                            'lot_mult': lot_mult
                        }
                        
        # Daily Scenario Classification
        day_r = sum(t['r_pnl'] for t in daily_trades)
        if len(daily_trades) == 0:
            scen = 'NO_TRADES'
        elif len(daily_trades) == 1:
            if daily_trades[0]['exit_reason'] == 'TP':
                scen = 'SCENARIO_A' # Win Trade 1 (+2R)
            else:
                scen = 'LOSS_NO_T2' # Lost Trade 1 (-1R), no Trade 2
        else: # 2 trades
            t1_win = daily_trades[0]['exit_reason'] == 'TP'
            t2_win = daily_trades[1]['exit_reason'] == 'TP'
            if not t1_win and t2_win:
                scen = 'SCENARIO_B' # Lost T1, Won T2 (+1R net)
            elif not t1_win and not t2_win:
                scen = 'SCENARIO_C' # Lost both (-2R net)
            else:
                scen = 'OTHER_2T'
                
        daily_summaries.append({
            'date': d,
            'scenario': scen,
            'day_r': day_r,
            'trades': len(daily_trades)
        })
        
    return pd.DataFrame(trades), pd.DataFrame(daily_summaries)


def calculate_metrics(trades_df, days_df):
    """
    Computes professional quantitative performance statistics.
    """
    if trades_df.empty:
        return {}
        
    total_trades = len(trades_df)
    wins = trades_df[trades_df['r_pnl'] > 0]
    losses = trades_df[trades_df['r_pnl'] <= 0]
    
    win_count = len(wins)
    loss_count = len(losses)
    win_rate = (win_count / total_trades) * 100.0
    
    total_r = trades_df['r_pnl'].sum()
    avg_r = trades_df['r_pnl'].mean()
    
    gross_profit = wins['r_pnl'].sum()
    gross_loss = abs(losses['r_pnl'].sum())
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else np.nan
    
    trades_df = trades_df.copy()
    trades_df['cum_r'] = trades_df['r_pnl'].cumsum()
    trades_df['peak_r'] = trades_df['cum_r'].cummax()
    trades_df['drawdown_r'] = trades_df['cum_r'] - trades_df['peak_r']
    max_dd_r = trades_df['drawdown_r'].min()
    
    streak = 0
    max_win_streak = 0
    max_loss_streak = 0
    for r in trades_df['r_pnl']:
        if r > 0:
            streak = (streak + 1) if streak > 0 else 1
            max_win_streak = max(max_win_streak, streak)
        else:
            streak = (streak - 1) if streak < 0 else -1
            max_loss_streak = max(max_loss_streak, abs(streak))
            
    daily_r = days_df.set_index('date')['day_r']
    if len(daily_r) > 1 and daily_r.std() > 0:
        sharpe = (daily_r.mean() / daily_r.std()) * np.sqrt(252)
    else:
        sharpe = 0.0
        
    scenarios = days_df['scenario'].value_counts().to_dict()
    
    return {
        'total_trades': total_trades,
        'win_count': win_count,
        'loss_count': loss_count,
        'win_rate': win_rate,
        'total_r': total_r,
        'avg_r': avg_r,
        'gross_profit_r': gross_profit,
        'gross_loss_r': gross_loss,
        'profit_factor': profit_factor,
        'max_dd_r': max_dd_r,
        'max_win_streak': max_win_streak,
        'max_loss_streak': max_loss_streak,
        'sharpe_ratio': sharpe,
        'scenarios': scenarios,
        'total_days': len(days_df)
    }
