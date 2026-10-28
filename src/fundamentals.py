"""Date-aware fundamentals; unavailable values are explicit, never synthesized."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO
import math
import pandas as pd
import requests


def _history(frame, columns):
    if not set(['date', *columns]).issubset(frame.columns):
        raise ValueError('missing required columns')
    out = frame.copy()
    out['date'] = pd.to_datetime(out['date'], errors='coerce')
    for column in columns:
        out[column] = pd.to_numeric(out[column], errors='coerce')
    if out['date'].isna().any() or (out['date'] > pd.Timestamp(date.today())).any():
        raise ValueError('invalid/future date')
    if out['date'].duplicated().any():
        raise ValueError('duplicate dates')
    return out.sort_values('date').reset_index(drop=True)


def analyze_shares(frame, source='unknown', unit='份', jump_threshold=0.30):
    """Changes are observation intervals, not calendar days. Missing gaps are flagged."""
    result = dict(available=False, source=source, unit='份', date=None, shares=None,
                  change1=None, change5=None, change20=None, state=None, reasons=[])
    if frame.empty:
        result['reasons'] = ['份额数据不可用']
        return result
    data = _history(frame, ['shares'])
    scale = {'份': 1, '万份': 10_000, '亿份': 100_000_000}.get(unit)
    if scale is None:
        raise ValueError('unsupported shares unit')
    data['shares'] *= scale
    if data['shares'].isna().any() or not data['shares'].map(math.isfinite).all() or (data['shares'] <= 0).any():
        raise ValueError('invalid shares')
    result.update(date=data.date.iloc[-1].date().isoformat(), shares=float(data.shares.iloc[-1]))
    # Known missing weekdays are conservative: exchange holiday calendar is not inferred.
    gaps = data.date.diff().dt.days.fillna(1)
    if (gaps > 4).any():
        result['reasons'].append('观察间隔不完整，变化率按可用观察值计算，不能视为连续交易日')
    jumps = data.shares.pct_change().abs() > jump_threshold
    if jumps.any():
        result['reasons'].append('份额异常跳变，需核对拆分/合并或数据单位；暂停流向信号')
        return result
    for n in (1, 5, 20):
        if len(data) > n:
            result[f'change{n}'] = float(data.shares.iloc[-1] / data.shares.iloc[-n-1] - 1)
    change = result['change5']
    result.update(available=True, state=None if change is None else '流入' if change > .01 else '流出' if change < -.01 else '稳定')
    result['reasons'].append('份额变化不是资金净流量；未计价格与申赎时间差')
    return result


def fetch_shares(symbol, as_of, timeout=12):
    """SSE official scale table; already normalized by AKShare definition to shares."""
    if not str(symbol).startswith(('5', '6')):
        raise ValueError('SZSE shares endpoint lacks a verified as-of date; unavailable')
    day = pd.Timestamp(as_of)
    if day.date() > date.today():
        raise ValueError('future request')
    response = requests.get('https://query.sse.com.cn/commonQuery.do', params={
        'isPagination':'true', 'pageHelp.pageSize':'10000', 'pageHelp.pageNo':'1',
        'sqlId':'COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L', 'STAT_DATE':day.strftime('%Y-%m-%d')},
        headers={'Referer':'https://www.sse.com.cn/', 'User-Agent':'Mozilla/5.0'}, timeout=timeout)
    response.raise_for_status()
    records = response.json().get('result', [])
    rows = [{'date': row['STAT_DATE'], 'shares':float(row['TOT_VOL'])*10000,
             'source':'SSE official ETF scale (份)'} for row in records if str(row.get('SEC_CODE')) == str(symbol)]
    return pd.DataFrame(rows, columns=['date','shares','source'])
