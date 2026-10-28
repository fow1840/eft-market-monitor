"""Trailing daily indicators. Returns are fractions; no forward fill or future data."""
import numpy as np
import pandas as pd


def calculate_indicators(frame: pd.DataFrame) -> pd.DataFrame:
    """Input must be chronological with unique dates; never silently reorders data.

    drawdown60 is close relative to the trailing 60-session closing high.
    volume_ratio includes the current day's volume in the trailing 20-day mean.
    """
    if not {'close', 'volume'}.issubset(frame.columns):
        raise ValueError('close and volume are required')
    result = frame.copy()
    if 'date' in result:
        dates = pd.to_datetime(result['date'], errors='raise')
        if dates.isna().any() or dates.duplicated().any() or not dates.is_monotonic_increasing:
            raise ValueError('dates must be unique and chronological')
    for column in ['close', 'volume']:
        result[column] = pd.to_numeric(result[column], errors='raise')
        observed = result[column].dropna()
        if not np.isfinite(observed).all() or (observed < 0).any():
            raise ValueError('prices and volume must be finite and nonnegative')
    if (result['close'].dropna() == 0).any():
        raise ValueError('close must be positive')
    close = result['close']
    for window in (5, 20, 60):
        result[f'ma{window}'] = close.rolling(window, min_periods=window).mean()
    for window in (20, 60):
        result[f'return{window}'] = close.pct_change(window, fill_method=None)
    result['drawdown60'] = close / close.rolling(60, min_periods=60).max() - 1
    average_volume = result['volume'].rolling(20, min_periods=20).mean()
    result['volume_ratio'] = result['volume'] / average_volume.replace(0, np.nan)
    result['trend'] = '数据不足'
    ready = result[['close', 'ma20', 'ma60']].notna().all(axis=1)
    result.loc[ready, 'trend'] = '中性'
    result.loc[ready & (close > result['ma20']) & (result['ma20'] > result['ma60']), 'trend'] = '强'
    result.loc[ready & (close < result['ma20']) & (result['ma20'] < result['ma60']), 'trend'] = '弱'
    change = close.diff()
    result['volume_state'] = '数据不足'
    volume_ready = change.notna() & result['volume_ratio'].notna()
    result.loc[volume_ready & (change == 0), 'volume_state'] = '平量平价'
    for rising, direction in [(True, '上涨'), (False, '下跌')]:
        mask = volume_ready & ((change > 0) if rising else (change < 0))
        result.loc[mask & (result['volume_ratio'] >= 1), 'volume_state'] = '放量' + direction
        result.loc[mask & (result['volume_ratio'] < 1), 'volume_state'] = '缩量' + direction
    return result


def summarize_indicators(frame: pd.DataFrame) -> dict:
    calculated = calculate_indicators(frame)
    if calculated.empty:
        return {'trend': '数据不足', 'volume_state': '数据不足'}
    return calculated.iloc[-1].where(calculated.iloc[-1].notna(), None).to_dict()
