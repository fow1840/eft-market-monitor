"""Dated index price history, stored separately from ETF shares/volume units."""
from io import StringIO
import multiprocessing as mp
from queue import Empty
import sqlite3
import pandas as pd
from src.fundamentals import INDEX_CODES


def _index_worker(queue,index):
    try:
        import akshare as ak
        code=INDEX_CODES[index]
        prefix='sz' if code.startswith('399') else 'sh'
        frame=ak.stock_zh_index_daily(symbol=prefix+code)
        queue.put(('ok',frame[['date','open','high','low','close','volume']].to_json(orient='records',date_format='iso')))
    except Exception as exc:queue.put(('error',type(exc).__name__))


def fetch_index(index,timeout=20):
    if index not in INDEX_CODES:raise ValueError('unsupported index')
    context=mp.get_context('spawn');queue=context.Queue();process=context.Process(target=_index_worker,args=(queue,index));process.start()
    try:
        try:status,payload=queue.get(timeout=timeout)
        except Empty as exc:raise TimeoutError('index request timeout') from exc
        if status!='ok':raise RuntimeError(payload)
        frame=pd.read_json(StringIO(payload))
        return validate_index(frame)
    finally:
        if process.is_alive():process.terminate()
        process.join(timeout=3);queue.close()


def validate_index(frame):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    import numpy as np
    frame=frame.copy()
    needed=['date','open','high','low','close','volume']
    if frame.empty or not set(needed)<=set(frame):raise ValueError('index schema/empty')
    frame=frame[needed]
    frame['date']=pd.to_datetime(frame.date,errors='coerce')
    for col in needed[1:]:frame[col]=pd.to_numeric(frame[col],errors='coerce')
    if frame.isna().any().any() or not np.isfinite(frame[needed[1:]]).all().all():raise ValueError('invalid index numeric/date')
    if frame.date.duplicated().any():raise ValueError('duplicate index dates')
    if (frame[['open','high','low','close']]<=0).any().any() or (frame.volume<0).any():raise ValueError('invalid index prices')
    if (frame.high<frame[['open','low','close']].max(axis=1)).any() or (frame.low>frame[['open','high','close']].min(axis=1)).any():raise ValueError('invalid index OHLC')
    now=datetime.now(ZoneInfo('Asia/Shanghai'))
    if (frame.date.dt.date>now.date()).any():raise ValueError('future index date')
    if (now.hour,now.minute)<(15,30):frame=frame[frame.date.dt.date<now.date()]
    return frame.sort_values('date').reset_index(drop=True)


def update_index(path,index,fetcher=fetch_index):
    from contextlib import closing
    frame=validate_index(fetcher(index))
    with closing(sqlite3.connect(path,timeout=10)) as db,db:
        db.execute('CREATE TABLE IF NOT EXISTS index_quotes (name TEXT,date TEXT,open REAL,high REAL,low REAL,close REAL,volume REAL,source TEXT,PRIMARY KEY(name,date))')
        rows=[(index,str(row.date.date()),row.open,row.high,row.low,row.close,row.volume,'Sina via AKShare; volume source units') for row in frame.itertuples(index=False)]
        db.executemany('INSERT OR REPLACE INTO index_quotes VALUES (?,?,?,?,?,?,?,?)',rows)
    return {'rows':len(frame),'date':str(frame.date.max().date()),'source':'Sina via AKShare'}
