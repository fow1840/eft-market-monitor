"""Read-only dashboard assembly; rendering never triggers network calls."""
from datetime import datetime, timedelta
import sqlite3
from zoneinfo import ZoneInfo
import pandas as pd
from src.market_data import read_quotes
from src.indicators import summarize_indicators
from src.history import latest_observation
from src.signals import market_state, LABELS


def build_dashboard(path, symbol='510300', *, now=None):
    now = now or datetime.now(ZoneInfo('Asia/Shanghai'))
    if now.tzinfo is None:
        raise ValueError('timezone-aware timestamp required')
    now = now.astimezone(ZoneInfo('Asia/Shanghai'))
    today = now.date()
    cutoff = today if (now.hour, now.minute) >= (15, 30) else today - timedelta(days=1)
    warnings = []
    try:
        quotes = read_quotes(path, symbol)
        # Clock gating is repeated here because tests and callers can supply data.
        quotes = quotes[pd.to_datetime(quotes['date']).dt.date <= cutoff].reset_index(drop=True)
        summary = summarize_indicators(quotes) if not quotes.empty else {}
    except (ValueError, OSError, sqlite3.Error, pd.errors.DatabaseError):
        quotes = pd.DataFrame(columns=['date', 'open', 'high', 'low', 'close', 'volume', 'amount'])
        summary = {}
        warnings.append('本地行情不可读或未通过校验，保留原文件；请检查数据')
    # Holidays are not fabricated as missing sessions. Without a verified exchange
    # calendar, >4 calendar days is a conservative unavailability gate, not a
    # declaration that trading sessions are missing.
    stale = quotes.empty or (today - quotes.date.iloc[-1].date()).days > 4
    trend = {'state': summary.get('trend', '数据不足'), **summary}
    volume = {'state': summary.get('volume_state', '数据不足'),
              'volume_ratio': summary.get('volume_ratio'), 'date': summary.get('date'),
              'source': summary.get('source')}
    if not quotes.empty and float(quotes['volume'].iloc[-1]) == 0:
        stale = True
        warnings.append('最新交易日零成交量，可能暂停交易；暂不产生方向判断')
    if stale:
        trend['state'] = volume['state'] = '数据不足'
        warnings.append('行情缺失或超过4个日历日未更新；节假日不补造行情，不产生方向判断')
    try:
        from src.calendar import load_calendar, latest_completed_session
        calendar = load_calendar()
        expected = latest_completed_session(now, calendar)
        if expected is not None and not quotes.empty:
            recent = calendar[calendar.date <= expected][-60:]
            observed = set(pd.to_datetime(quotes.date).dt.normalize())
            if quotes.date.iloc[-1].date() < expected or any(day not in observed for day in recent):
                trend['state'] = volume['state'] = '数据不足'
                warnings.append('行情未覆盖最新已收盘交易日或最近60个交易日存在缺失')
    except (OSError, ValueError, KeyError):
        expected = None
        warnings.append('本地交易日历不可用，无法确认最新交易日')
    observations = {}
    for kind, key, max_age in [('shares', symbol, 4), ('valuation', '沪深300', 45), ('breadth', 'market', 4)]:
        try:
            item = latest_observation(path, kind, key) or {'available': False, 'state': None, 'reasons': ['本地尚无数据']}
            observed_day = datetime.fromisoformat(str(item['date'])).date() if item.get('date') else None
            allowed_day = cutoff
            invalid = (not item.get('available', False) or observed_day is None
                       or observed_day > allowed_day or (today - observed_day).days > max_age
                       or item.get('state') not in LABELS[kind]
                       or (kind == 'breadth' and expected is not None and observed_day != expected))
            if invalid:
                item = {**item, 'state': None, 'available': False}
                warnings.append(f'{kind} 数据不可用、未收盘或过期')
        except (ValueError, TypeError, OSError, sqlite3.Error, pd.errors.DatabaseError):
            item = {'available': False, 'state': None, 'reasons': ['本地数据不可读，保留原文件']}
            warnings.append(f'{kind} 本地数据未通过校验')
        observations[kind] = item
    dimensions = {'trend': trend['state'], 'volume': volume['state'],
                  **{key: value.get('state') for key, value in observations.items()}}
    market = market_state(dimensions)
    if not market['complete']:
        warnings.append('五维数据不足；中性仅为占位，不代表风险低')
    return dict(date=str(today), symbol=symbol, trend=trend, volume=volume, market=market,
                quotes=quotes, warnings=warnings, **observations)
