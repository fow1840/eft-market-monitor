"""Local snapshots and portfolio. No user data is sent over the network."""
from datetime import date
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3


@contextmanager
def _connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db=sqlite3.connect(path, timeout=10)
    try:
        db.execute('CREATE TABLE IF NOT EXISTS snapshots (date TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS local_portfolio (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS observations (kind TEXT, symbol TEXT, date TEXT, payload TEXT NOT NULL, PRIMARY KEY(kind,symbol,date))')
        with db:
            yield db
    finally:
        db.close()


def save_snapshot(path, day, payload):
    day=date.fromisoformat(str(day)).isoformat()
    value=json.dumps(payload,ensure_ascii=False,allow_nan=False)
    with _connect(path) as db:
        db.execute('INSERT OR REPLACE INTO snapshots VALUES (?,?)',(day,value))


def query_snapshots(path, start, end):
    start=date.fromisoformat(str(start)); end=date.fromisoformat(str(end))
    if start>end: raise ValueError('起始日期不能晚于结束日期')
    with _connect(path) as db:
        rows=db.execute('SELECT date,payload FROM snapshots WHERE date BETWEEN ? AND ? ORDER BY date',(str(start),str(end))).fetchall()
    return [{'date':day,'payload':json.loads(payload)} for day,payload in rows]


def save_portfolio(path, rows):
    from src.portfolio import analyze_portfolio
    result=analyze_portfolio(rows)
    safe=result['holdings'][['name','amount','category','target_pct']].to_dict('records')
    with _connect(path) as db:
        db.execute('INSERT OR REPLACE INTO local_portfolio VALUES (1,?)',(json.dumps(safe,ensure_ascii=False,allow_nan=False),))


def load_portfolio(path):
    with _connect(path) as db:
        row=db.execute('SELECT payload FROM local_portfolio WHERE id=1').fetchone()
    return json.loads(row[0]) if row else []


def save_observation(path, kind, symbol, day, payload):
    day = date.fromisoformat(str(day)).isoformat()
    if payload.get('date') is not None and str(payload['date'])[:10] != day:
        raise ValueError('观察值日期与存储日期不一致')
    with _connect(path) as db:
        db.execute('INSERT OR REPLACE INTO observations VALUES (?,?,?,?)',
            (kind,symbol,str(day),json.dumps(payload,ensure_ascii=False,allow_nan=False)))


def latest_observation(path, kind, symbol='market'):
    with _connect(path) as db:
        row=db.execute('SELECT date,payload FROM observations WHERE kind=? AND symbol=? ORDER BY date DESC LIMIT 1',(kind,symbol)).fetchone()
    return {**json.loads(row[1]), 'date': row[0]} if row else None


def query_observations(path, kind, symbol):
    with _connect(path) as db:
        rows=db.execute('SELECT date,payload FROM observations WHERE kind=? AND symbol=? ORDER BY date',(kind,symbol)).fetchall()
    return [{**json.loads(payload), 'date': day} for day,payload in rows]
