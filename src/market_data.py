"""Validated daily ETF quotes with bounded subprocess fetches and SQLite cache."""
from __future__ import annotations
import json
from contextlib import contextmanager
import multiprocessing as mp
from pathlib import Path
import sqlite3
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd

ETF_UNIVERSE = {
    '510300': '沪深300ETF', '588000': '科创50ETF', '159338': 'A500ETF',
    '159915': '创业板ETF', '159665': '半导体ETF', '159992': '创新药ETF', '518880': '黄金ETF',
}
COLUMNS = ['date', 'open', 'high', 'low', 'close', 'volume', 'amount']


def validate_quotes(frame: pd.DataFrame, today=None) -> pd.DataFrame:
    missing = set(COLUMNS) - set(frame.columns)
    if missing or frame.empty:
        raise ValueError(f'行情为空或字段缺失: {sorted(missing)}')
    data = frame[COLUMNS].copy()
    data['date'] = pd.to_datetime(data['date'], errors='coerce').dt.normalize()
    for col in COLUMNS[1:]:
        data[col] = pd.to_numeric(data[col], errors='coerce')
    if data.isna().any().any() or not np.isfinite(data[COLUMNS[1:]].to_numpy()).all():
        raise ValueError('行情含空值或非有限数值')
    if ((data[['open','high','low','close']] <= 0).any().any()
        or (data[['volume','amount']] < 0).any().any()
        or (data['high'] < data[['open','close','low']].max(axis=1)).any()
        or (data['low'] > data[['open','close','high']].min(axis=1)).any()):
        raise ValueError('OHLC 或量额不合法')
    now = pd.Timestamp(today or datetime.now(ZoneInfo('Asia/Shanghai')).date()).normalize()
    if (data['date'] > now).any() or (data['date'].dt.dayofweek > 4).any():
        raise ValueError('行情日期在未来或非交易工作日')
    # Identical duplicates are harmless; conflicting observations require investigation.
    duplicates = data[data.duplicated('date', keep=False)]
    if not duplicates.empty and duplicates.groupby('date')[COLUMNS[1:]].nunique().gt(1).any().any():
        raise ValueError('同日行情冲突')
    data = data.drop_duplicates('date').sort_values('date').reset_index(drop=True)
    if data['close'].pct_change().abs().gt(.35).any():
        raise ValueError('收盘价异常跳变，须核查复权/分红/拆分')
    return data


def _worker(queue, symbol, provider):
    try:
        import akshare as ak
        if provider == 'eastmoney':
            data = ak.fund_etf_hist_em(symbol=symbol, start_date='20180101', adjust='')
            data = data.rename(columns={'日期':'date','开盘':'open','最高':'high','最低':'low','收盘':'close','成交量':'volume','成交额':'amount'})
            # Eastmoney reports ETF volume in lots of 100 shares.
            data['volume'] = pd.to_numeric(data['volume']) * 100
        else:
            prefix = 'sh' if symbol.startswith(('5','6')) else 'sz'
            data = ak.fund_etf_hist_sina(symbol=prefix + symbol)
        queue.put(('ok', data[COLUMNS].to_json(orient='records', date_format='iso')))
    except Exception as exc:
        queue.put(('error', type(exc).__name__))


def fetch_quotes(symbol: str, provider='eastmoney', timeout=25) -> pd.DataFrame:
    if symbol not in ETF_UNIVERSE:
        raise ValueError('不支持的 ETF 代码')
    if provider not in ('eastmoney', 'sina') or not 0 < timeout <= 120:
        raise ValueError('行情 provider 或超时设置不合法')
    ctx = mp.get_context('spawn')
    queue = ctx.Queue()
    process = ctx.Process(target=_worker, args=(queue, symbol, provider))
    process.start()
    try:
        from queue import Empty
        try:
            status, payload = queue.get(timeout=timeout)
        except Empty as exc:
            raise TimeoutError(f'{provider} 请求超时') from exc
        if status != 'ok':
            raise RuntimeError(f'{provider}: {payload}')
        from io import StringIO
        return validate_quotes(pd.read_json(StringIO(payload)))
    finally:
        if process.is_alive():
            process.terminate()
        process.join(timeout=3)
        queue.close()


@contextmanager
def connect_quotes(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    try:
        connection.execute('''CREATE TABLE IF NOT EXISTS quotes (
      symbol TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL,
      volume REAL, amount REAL, source TEXT, fetched_at TEXT,
      PRIMARY KEY(symbol,date))''')
        with connection:
            yield connection
    finally:
        connection.close()


def save_quotes(path: Path, symbol: str, frame: pd.DataFrame, source: str):
    if symbol not in ETF_UNIVERSE:
        raise ValueError('不支持的 ETF 代码')
    data = validate_quotes(frame)
    now = datetime.now(ZoneInfo('Asia/Shanghai'))
    if (now.hour, now.minute) < (15, 30):
        data = data[data['date'].dt.date < now.date()]
    fetched = datetime.now(timezone.utc).isoformat()
    rows = [(symbol, row.date.strftime('%Y-%m-%d'), row.open,row.high,row.low,row.close,row.volume,row.amount,source,fetched)
            for row in data.itertuples(index=False)]
    with connect_quotes(path) as db:
        db.executemany('INSERT OR REPLACE INTO quotes VALUES (?,?,?,?,?,?,?,?,?,?)', rows)


def read_quotes(path: Path, symbol: str) -> pd.DataFrame:
    with connect_quotes(path) as db:
        data = pd.read_sql_query('SELECT * FROM quotes WHERE symbol=? ORDER BY date', db, params=(symbol,))
    if not data.empty:
        # Disk corruption/manual edits must not bypass ingestion validation.
        validated = validate_quotes(data)
        data['date'] = pd.to_datetime(data['date'])
        data = data[data['date'].isin(validated['date'])].drop_duplicates('date').reset_index(drop=True)
        now = datetime.now(ZoneInfo('Asia/Shanghai'))
        # Intraday API bars are not completed daily data.
        if (now.hour, now.minute) < (15, 30):
            data = data[data['date'].dt.date < now.date()].reset_index(drop=True)
    return data


def update_quotes(path: Path, symbol: str, *, force=False, fetcher=fetch_quotes, retries=2, cache_hours=6) -> dict:
    if not isinstance(retries, int) or not 1 <= retries <= 3:
        raise ValueError('重试次数必须为1至3')
    try:
        cached = read_quotes(path, symbol)
    except (ValueError, sqlite3.Error, pd.errors.DatabaseError) as exc:
        # Preserve damaged files. A database fault needs explicit repair, not reset.
        return {'data':pd.DataFrame(columns=COLUMNS), 'cached':False,
                'error':'本地行情缓存不可读: ' + type(exc).__name__, 'source':None}
    if not cached.empty and not force:
        try:
            fetched_at = datetime.fromisoformat(cached['fetched_at'].iloc[-1])
            age = datetime.now(timezone.utc) - fetched_at
            fresh_cache = 0 <= age.total_seconds() < cache_hours * 3600
            local_now = datetime.now(ZoneInfo('Asia/Shanghai'))
            close_time = local_now.replace(hour=15, minute=30, second=0, microsecond=0)
            if local_now.weekday() < 5 and local_now >= close_time and fetched_at < close_time:
                fresh_cache = False
        except (TypeError, ValueError):
            fresh_cache = False
        if fresh_cache:
            return {'data':cached, 'cached':True, 'error':None, 'source':cached['source'].iloc[-1]}
    errors = []
    for provider in ('eastmoney','sina'):
        for attempt in range(retries):
            try:
                data = validate_quotes(fetcher(symbol, provider=provider))
                if len(data) < 250:
                    raise ValueError('历史行情不足250个交易日')
                save_quotes(path,symbol,data,provider)
                return {'data':read_quotes(path,symbol), 'cached':False, 'error':None, 'source':provider}
            except (Exception,) as exc:
                errors.append(f'{provider}/{attempt+1}: {type(exc).__name__}')
                if attempt + 1 < retries:
                    time.sleep(.25 * (attempt + 1))
    return {'data':cached, 'cached':True, 'error':'; '.join(errors), 'source':None if cached.empty else cached['source'].iloc[-1]}
