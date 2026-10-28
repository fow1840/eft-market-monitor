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


INDEX_CODES = {'沪深300':'000300', 'A500':'000510', '科创50':'000688', '创业板':'399006'}


def analyze_valuation(frame, source='unknown', min_history=250):
    """Empirical percentile includes only observations through latest date; no fill."""
    result = dict(available=False, source=source, date=None, pe=None, pb=None,
                  dividend_yield=None, pe_percentile=None, pb_percentile=None,
                  state=None, reasons=[], history_count=0)
    if frame.empty:
        result['reasons'] = ['估值数据不可用']
        return result
    data = _history(frame, ['pe', 'pb', 'dividend_yield'])
    result['date'] = data.date.iloc[-1].date().isoformat()
    result['history_count'] = len(data)
    for column in ('pe','pb','dividend_yield'):
        value = data[column].iloc[-1]
        if pd.notna(value) and math.isfinite(value) and (value > 0 if column != 'dividend_yield' else value >= 0):
            result[column] = float(value)
    percentiles = []
    for column in ('pe','pb'):
        history = data[column].dropna()
        history = history[(history > 0) & history.map(math.isfinite)]
        if len(history) >= min_history and result[column] is not None:
            rank = float((history <= result[column]).mean())
            result[f'{column}_percentile'] = rank
            percentiles.append(rank)
    result['available'] = result['pe'] is not None or result['pb'] is not None
    if percentiles:
        avg = sum(percentiles) / len(percentiles)
        result['state'] = '偏低' if avg <= .3 else '偏高' if avg >= .7 else '中性'
    else:
        result['reasons'].append(f'不足{min_history}个有效历史观察值，不输出历史估值判断')
    if result['pb'] is None:
        result['reasons'].append('来源未提供可验证PB，不以其他指数替代')
    return result


def fetch_valuation(index, timeout=12):
    """CSIndex official indicator workbook: PE1 and dividend1, no PB supplied."""
    code = INDEX_CODES.get(index,index)
    if code not in INDEX_CODES.values():
        raise ValueError('unsupported index')
    url = f'https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile/indicator/{code}indicator.xls'
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    data = pd.read_excel(BytesIO(response.content))
    if data.shape[1] != 10:
        raise ValueError('CSIndex schema changed')
    data.columns = ['date','code','full_name','name','en_full_name','en_name','pe','pe2','dividend_yield','dividend2']
    data['date'] = pd.to_datetime(data['date'].astype(str), format='%Y%m%d', errors='coerce')
    data['pb'] = float('nan')
    data['source'] = 'CSIndex official indicator (PE1; dividend yield %)'
    return data[['date','pe','pb','dividend_yield','source']]
