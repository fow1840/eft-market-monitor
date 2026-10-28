"""Dated supplementary LG valuations, kept distinct from official PE1 data.

AKShare 1.20.1 documents 沪深300 for stock_index_pe_lg/pb_lg but does not
support A500/科创50/创业板 in those functions (创业板50 is NOT 创业板).
FundDB's former index_value_hist_funddb is absent in this AKShare version.
No undocumented index substitutions or stale official/provider mixing occur.
"""
from __future__ import annotations
from datetime import datetime
import multiprocessing as mp
from queue import Empty
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd

SOURCE = '乐咕乐股 via AKShare stock_index_pe_lg / stock_index_pb_lg'
ALIASES = {'沪深300': '沪深300', '000300': '沪深300', 'A500': 'A500', '000510': 'A500',
           '科创50': '科创50', '000688': '科创50', '创业板': '创业板', '399006': '创业板'}
DEFINITIONS = {'pe': '滚动市盈率（AKShare 字段：滚动市盈率；源字段 addTtmPe）',
               'pb': '市净率（AKShare 字段：市净率；源字段 addPb）'}


def _empty(index):
    return dict(index=index, available=False, source=SOURCE, date=None, pe=None, pb=None,
                dividend_yield=None, pe_percentile=None, pb_percentile=None, state=None,
                history_count=0, reasons=[], fields={}, history_frequency=None,
                percentile_basis='同一提供方、同一指标定义的有效观察值经验百分位，非日频百分位',
                stale=False)


def _legu_worker(queue):
    """Run unbounded upstream helpers in a killable, isolated subprocess."""
    try:
        import akshare as ak
        payload, errors = {}, []
        for field, function in [('pe', ak.stock_index_pe_lg), ('pb', ak.stock_index_pb_lg)]:
            try:
                frame = function(symbol='沪深300')
                # Dates are serialized without time-zone/epoch ambiguity.
                frame['日期'] = frame['日期'].astype(str)
                payload[field] = frame.to_dict(orient='records')
            except Exception as exc:
                errors.append(f'{field}: {type(exc).__name__}')
        queue.put({'data': payload, 'errors': errors})
    except Exception as exc:
        queue.put({'data': {}, 'errors': [type(exc).__name__]})


def _bounded_fetch(timeout, worker=None):
    if not np.isfinite(timeout) or not 0 < timeout <= 120:
        raise ValueError('timeout must be in (0,120] seconds')
    ctx = mp.get_context('spawn')
    queue = ctx.Queue()
    process = ctx.Process(target=worker or _legu_worker, args=(queue,))
    process.start()
    try:
        try:
            return queue.get(timeout=timeout)
        except Empty as exc:
            raise TimeoutError('LG public valuation request exceeded bounded deadline') from exc
    finally:
        if process.is_alive():
            process.terminate()
        process.join(timeout=2)
        if process.is_alive():
            process.kill()
            process.join(timeout=2)
        queue.close()


def _field_history(records, field, as_of):
    frame = pd.DataFrame(records)
    column = {'pe': '滚动市盈率', 'pb': '市净率'}[field]
    if frame.empty or not {'日期', column}.issubset(frame.columns):
        raise ValueError(f'{field} schema missing or empty')
    dates = pd.to_datetime(frame['日期'], errors='coerce')
    values = pd.to_numeric(frame[column], errors='coerce')
    if dates.isna().any() or dates.duplicated().any() or (dates > as_of).any():
        raise ValueError(f'{field} dates invalid, duplicate or future')
    valid = values.notna() & np.isfinite(values) & values.gt(0)
    out = pd.DataFrame({'date': dates[valid], 'value': values[valid]}).sort_values('date')
    if out.empty:
        raise ValueError(f'{field} has no finite positive observations')
    # Do not silently use an older valid row when the latest provider value is invalid.
    if out.date.iloc[-1] != dates.max():
        raise ValueError(f'{field} latest value invalid')
    gaps = out.date.diff().dt.days.dropna()
    median_gap = float(gaps.median()) if len(gaps) else None
    frequency = ('月度/不规则观察' if median_gap is not None and median_gap >= 20
                 else '日度/不规则观察（未独立核验交易日历）')
    return out, {'source': SOURCE, 'definition': DEFINITIONS[field],
                 'date': out.date.iloc[-1].date().isoformat(),
                 'value': float(out.value.iloc[-1]), 'observations': len(out),
                 'first_date': out.date.iloc[0].date().isoformat(),
                 'frequency': frequency, 'median_gap_calendar_days': median_gap}


def fetch_valuation_fallback(index, timeout=20, *, min_history=250, as_of=None):
    """Return analyze_valuation-compatible result with per-field provenance.

    This fallback never merges CSIndex PE1 with LG TTM/PB. Root callers can keep
    official_fields separately. Unsupported indices return explicit unavailable.
    Historical percentiles refer to observation frequency, not 250 daily bars.
    """
    normalized = ALIASES.get(str(index))
    result = _empty(normalized or str(index))
    if normalized is None:
        result['reasons'] = ['不支持的指数；未替换为其他指数']
        return result
    if normalized != '沪深300':
        result['reasons'] = [f'LG 已文档化接口不支持{normalized}；创业板50不等同创业板，不替代。',
                             'AKShare 1.20.1 不含 index_value_hist_funddb；无已验证替代历史来源。']
        return result
    if not isinstance(min_history, int) or isinstance(min_history, bool) or min_history < 1:
        raise ValueError('min_history must be a positive integer')
    today = pd.Timestamp(datetime.now(ZoneInfo('Asia/Shanghai')).date())
    day = pd.Timestamp(as_of).normalize() if as_of is not None else today
    if day > today:
        raise ValueError('as_of cannot be in future')
    try:
        payload = _bounded_fetch(timeout)
    except (TimeoutError, OSError) as exc:
        result['reasons'] = [f'LG 数据降级：{type(exc).__name__}，不影响主系统']
        return result
    result['reasons'].extend(payload.get('errors', []))
    series = {}
    for field in ('pe', 'pb'):
        if field not in payload.get('data', {}):
            continue
        try:
            history, metadata = _field_history(payload['data'][field], field, day)
        except (ValueError, TypeError, KeyError) as exc:
            result['reasons'].append(f'{field} 校验失败：{exc}')
            continue
        percentile = float((history.value <= metadata['value']).mean()) if len(history) >= min_history else None
        metadata['percentile'] = percentile
        series[field] = history
        result['fields'][field] = metadata
    if not series:
        result['reasons'].append('无可验证的历史估值观察')
        return result
    latest_date = max(metadata['date'] for metadata in result['fields'].values())
    result['date'] = latest_date
    matched = []
    counts = []
    # A value on an earlier field date is only shown in fields, not as today's value.
    for field, metadata in result['fields'].items():
        if metadata['date'] == latest_date:
            result[field] = metadata['value']
            result[f'{field}_percentile'] = metadata['percentile']
            counts.append(metadata['observations'])
            if metadata['percentile'] is not None:
                matched.append(metadata['percentile'])
        else:
            result['reasons'].append(f'{field} 日期与最新观察不一致，只保留字段级日期，不合并为同日估值')
    result['history_count'] = min(counts) if counts else 0
    result['history_frequency'] = '；'.join(sorted({m['frequency'] for m in result['fields'].values()}))
    result['available'] = result['pe'] is not None or result['pb'] is not None
    result['stale'] = (day - pd.Timestamp(latest_date)).days > 10
    if result['stale']:
        result['reasons'].append('最新估值观察距请求日超过10个自然日，不输出当前状态')
    elif matched:
        average = sum(matched) / len(matched)
        result['state'] = '偏低' if average <= .3 else '偏高' if average >= .7 else '中性'
    else:
        result['reasons'].append(f'不足{min_history}条有效历史观察，未计算历史估值判断')
    result['reasons'].extend([
        'LG滚动PE和PB与中证指数官方PE1口径不同；仅作独立补充，不混合时间序列。',
        '历史可能是月度抽样；250条观察不代表250个连续交易日。百分位依赖样本区间。',
        '该来源未提供已验证股息率，保留为空；不以其他指数替代。',
        '历史接口为当前时点取得的数据，未证明历史发布时点，不直接用于无未来函数回测。'])
    return result
