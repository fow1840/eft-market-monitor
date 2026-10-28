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


def _rounded_limit(previous, ratio):
    return float((Decimal(str(previous)) * Decimal(str(ratio))).quantize(Decimal('.01'), rounding=ROUND_HALF_UP))


def analyze_breadth(frame, as_of, source='unknown', expected_count=None):
    """Only verified complete snapshots produce a market state; MA coverage is explicit."""
    result = dict(available=False, source=source, date=str(as_of), state=None, reasons=[],
                  advances=None, declines=None, unchanged=None, advance_ratio=None,
                  limit_up_count=None, limit_down_count=None, above_ma20_ratio=None,
                  above_ma60_ratio=None, turnover=None, observed_count=0,
                  expected_count=expected_count, coverage=None, ma20_coverage=0., ma60_coverage=0.)
    if frame.empty:
        result['reasons'].append('全A行情不可用')
        return result
    if pd.Timestamp(as_of).date() > date.today():
        raise ValueError('future breadth date')
    required = {'code','name','close','previous_close','amount'}
    if not required.issubset(frame.columns):
        raise ValueError('missing breadth columns')
    data = frame.copy()
    if data.code.duplicated().any():
        raise ValueError('duplicate stock codes')
    for column in ['close','previous_close','amount']:
        data[column] = pd.to_numeric(data[column], errors='coerce')
    # Suspensions/missing quotes do not become unchanged observations.
    valid = data[['close','previous_close','amount']].notna().all(axis=1)
    valid &= data.close.gt(0) & data.previous_close.gt(0) & data.amount.ge(0)
    valid &= data[['close','previous_close','amount']].apply(lambda col: col.map(math.isfinite)).all(axis=1)
    quoted = data[valid].copy()
    n = len(quoted)
    result['observed_count'] = len(data)
    result['quoted_count'] = n
    result['excluded_count'] = len(data)-n
    if expected_count is not None:
        if expected_count <= 0 or len(data) > expected_count:
            raise ValueError('invalid expected universe count')
        result['coverage'] = len(data) / expected_count
    if not n:
        result['reasons'].append('无有效报价')
        return result
    advances = int((quoted.close > quoted.previous_close).sum())
    declines = int((quoted.close < quoted.previous_close).sum())
    ratio = advances/n
    result.update(available=True, advances=advances, declines=declines,
                  unchanged=n-advances-declines, advance_ratio=ratio,
                  turnover=float(quoted.amount.sum()))
    complete = expected_count == len(data) and expected_count is not None
    for window in [20,60]:
        column = f'ma{window}'
        if column in quoted:
            values = pd.to_numeric(quoted[column], errors='coerce')
            valid_ma = values.gt(0) & values.map(lambda v: pd.notna(v) and math.isfinite(v))
            coverage = float(valid_ma.sum()/len(data))
            result[f'ma{window}_coverage'] = coverage
            if complete and valid_ma.all() and n == len(data):
                result[f'above_ma{window}_ratio'] = float((quoted.close > values).mean())
    # Published limits are preferred; inferred limits exclude newly-listed/unknown ages.
    for side in ('up','down'):
        column = f'limit_{side}'
        if column in quoted:
            limits = pd.to_numeric(quoted[column], errors='coerce')
            if limits.notna().all() and limits.gt(0).all():
                result[f'limit_{side}_count'] = int(((quoted.close >= limits-.005) if side == 'up' else (quoted.close <= limits+.005)).sum())
    inferred_up = inferred_down = 0
    inferred_valid = 0
    for row in quoted.to_dict('records'):
        if row.get('listed_sessions',0) <= 5:
            continue
        code, name = str(row['code']), str(row['name'])
        rate = .30 if code.startswith(('4','8','92')) else .20 if code.startswith(('30','68')) else .05 if 'ST' in name.upper() else .10
        inferred_up += row['close'] >= _rounded_limit(row['previous_close'],1+rate)-.005
        inferred_down += row['close'] <= _rounded_limit(row['previous_close'],1-rate)+.005
        inferred_valid += 1
    result.update(inferred_limit_up_count=int(inferred_up) if inferred_valid else None,
                  inferred_limit_down_count=int(inferred_down) if inferred_valid else None,
                  inferred_limit_coverage=inferred_valid/n)
    if result['limit_up_count'] is None:
        result['reasons'].append('未提供逐股官方涨跌停价，涨跌停数不可验证；板块推算单独列示')
    if not complete:
        result['reasons'].append('全A股票集合完整性未验证，不输出全市场状态')
    else:
        result['state'] = '强' if ratio >= .7 else '改善' if ratio >= .55 else '中性' if ratio >= .45 else '偏弱' if ratio >= .3 else '弱'
        result['reasons'].append(f'有效报价上涨比例{ratio:.1%}；停牌/无效报价{len(data)-n}只排除')
    if result['above_ma20_ratio'] is None or result['above_ma60_ratio'] is None:
        result['reasons'].append('逐股历史均线覆盖不足，不伪造MA20/MA60宽度')
    return result


def fetch_breadth(timeout=10, max_pages=80):
    """Bounded Eastmoney full-universe snapshot; rejects mixed quote dates."""
    rows = []
    total = None
    url = 'https://82.push2.eastmoney.com/api/qt/clist/get'
    for page in range(1,max_pages+1):
        response = requests.get(url, params={'pn':page,'pz':100,'po':1,'np':1,'fltt':2,'invt':2,
            'fid':'f12','fs':'m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048',
            'fields':'f2,f6,f12,f14,f18,f124'}, timeout=timeout)
        response.raise_for_status()
        payload = response.json().get('data') or {}
        count = payload.get('total')
        if count is None or (total is not None and count != total):
            raise ValueError('universe total missing/changed')
        total = count
        batch = payload.get('diff') or []
        if isinstance(batch,dict): batch=list(batch.values())
        rows.extend(batch)
        if len(rows) >= total: break
        if not batch: raise ValueError('incomplete pagination')
    else:
        raise ValueError('breadth page limit exceeded')
    if not rows: return analyze_breadth(pd.DataFrame(), date.today(), 'Eastmoney full A', total)
    dates = {pd.Timestamp(row['f124'],unit='s',tz='UTC').tz_convert('Asia/Shanghai').date().isoformat() for row in rows if row.get('f124')}
    if len(dates) != 1: raise ValueError('mixed/missing quote dates')
    frame = pd.DataFrame(rows).rename(columns={'f12':'code','f14':'name','f2':'close','f18':'previous_close','f6':'amount'})
    return analyze_breadth(frame, dates.pop(), 'Eastmoney full A realtime snapshot',total)
