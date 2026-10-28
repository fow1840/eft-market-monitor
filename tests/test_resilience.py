"""Independent T15 regression checks: preserve evidence and fail closed."""
from datetime import datetime
from zoneinfo import ZoneInfo
import sqlite3
import pandas as pd
import pytest
from src.storage import initialize_database
from src.market_data import save_quotes, read_quotes, update_quotes, validate_quotes
from src.history import save_observation, latest_observation, query_observations, query_snapshots
from src.dashboard import build_dashboard
from src.portfolio import risk_advice

TZ = ZoneInfo('Asia/Shanghai')


def bars(n=260, end='2025-01-02'):
    return pd.DataFrame(dict(date=pd.bdate_range(end=end, periods=n), open=10.,
        high=11., low=9., close=10., volume=100., amount=1000.))


def test_corrupted_sqlite_is_preserved_and_dashboard_degrades(tmp_path):
    path = tmp_path / 'corrupted.db'
    original = b'not a SQLite database; preserve this evidence\x00\x01'
    path.write_bytes(original)
    with pytest.raises(sqlite3.DatabaseError): initialize_database(path)
    result = update_quotes(path, '510300', fetcher=lambda *a, **k: pytest.fail('must not overwrite damaged database'))
    assert result['error'] and result['data'].empty
    dashboard = build_dashboard(path)
    assert dashboard['quotes'].empty
    assert not dashboard['market']['complete']
    assert path.read_bytes() == original


def test_normal_payload_date_roundtrip_and_conflict(tmp_path):
    path = tmp_path / 'observations.db'
    payload = {'date':'2025-01-02', 'available':True, 'state':'流入'}
    save_observation(path, 'shares', '510300', payload['date'], payload)
    assert latest_observation(path, 'shares', '510300') == payload
    assert query_observations(path, 'shares', '510300') == [payload]
    with pytest.raises(ValueError): save_observation(path, 'shares', '510300', '2025-01-03', payload)


def test_malformed_cached_ohlc_never_enters_signal_engine(tmp_path):
    path = tmp_path / 'market.db'
    save_quotes(path, '510300', bars(), 'fixture')
    with sqlite3.connect(path) as db:
        db.execute('UPDATE quotes SET high=0 WHERE date=(SELECT MAX(date) FROM quotes)')
    with pytest.raises(ValueError): read_quotes(path, '510300')
    dashboard = build_dashboard(path)
    assert not dashboard['market']['complete']
    assert dashboard['trend']['state'] == '数据不足'


@pytest.mark.parametrize('transform', [
    lambda x: x.assign(close=100.),
    lambda x: x.assign(volume=-1.),
    lambda x: x.drop(columns='amount'),
    lambda x: x.assign(amount=float('inf')),
])
def test_malformed_provider_never_overwrites_cache(tmp_path, transform):
    path = tmp_path / 'market.db'; data = bars()
    save_quotes(path, '510300', data, 'fixture')
    before = read_quotes(path, '510300')
    result = update_quotes(path, '510300', force=True, retries=1,
        fetcher=lambda *a, **k: transform(data))
    assert result['error'] and len(result['data']) == len(before)
    pd.testing.assert_frame_equal(before, read_quotes(path, '510300'))


def test_split_spike_is_quarantined():
    data = bars(); data.loc[len(data)-1, ['open','high','low','close']] *= 2
    with pytest.raises(ValueError, match='跳变'): validate_quotes(data)


def test_network_timeout_bounded_cache_fallback(tmp_path):
    path = tmp_path / 'market.db'; save_quotes(path, '510300', bars(), 'fixture')
    calls = []
    def timeout(*a, **k):
        calls.append(k['provider'])
        raise TimeoutError('secret_api_key_should_not_be_logged')
    result = update_quotes(path, '510300', force=True, retries=1, fetcher=timeout)
    assert calls == ['eastmoney', 'sina']
    assert len(result['data']) == 260 and result['error']
    assert 'secret_api_key' not in result['error']


def test_holiday_and_suspended_gaps_never_fabricated(tmp_path):
    data = bars().drop(index=[100,101,102]).reset_index(drop=True)
    checked = validate_quotes(data)
    assert len(checked) == len(data)
    path = tmp_path / 'market.db'; save_quotes(path, '510300', checked, 'fixture')
    assert len(read_quotes(path, '510300')) == len(data)


def test_stale_or_suspended_market_cannot_enable_extra_buy(tmp_path):
    path = tmp_path / 'market.db'; data = bars(); data.loc[len(data)-1, 'volume'] = 0
    save_quotes(path, '510300', data, 'fixture')
    result = build_dashboard(path, now=datetime(2025,1,2,16,tzinfo=TZ))
    assert result['trend']['state'] == '数据不足'
    state = result['market']['state'] if result['market']['complete'] else '数据不足'
    assert not risk_advice(0, 20, state)['allow_extra_buy']
    assert any('零成交量' in warning for warning in result['warnings'])


def test_future_and_intraday_fundamentals_not_directional(tmp_path):
    path = tmp_path / 'market.db'; save_quotes(path, '510300', bars(), 'fixture')
    for kind, symbol, label in [('shares','510300','流入'), ('valuation','沪深300','偏低'), ('breadth','market','强')]:
        save_observation(path,kind,symbol,'2025-01-03',{'date':'2025-01-03','available':True,'state':label})
    result = build_dashboard(path, now=datetime(2025,1,3,14,tzinfo=TZ))
    assert result['valuation']['state'] is None
    assert result['breadth']['state'] is None
    assert not result['shares']['available']
    result = build_dashboard(path, now=datetime(2025,1,2,16,tzinfo=TZ))
    assert not result['shares']['available']
    assert not result['market']['complete']


def test_intraday_bar_not_persisted_or_analyzed(tmp_path, monkeypatch):
    import src.market_data as market_data
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2025,1,3,14,0,tzinfo=TZ).astimezone(tz) if tz else datetime(2025,1,3,14)
    monkeypatch.setattr(market_data, 'datetime', Clock)
    path = tmp_path / 'market.db'
    save_quotes(path, '510300', bars(end='2025-01-03'), 'fixture')
    saved = read_quotes(path, '510300')
    assert str(saved.date.max().date()) == '2025-01-02'
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT MAX(date) FROM quotes').fetchone()[0] == '2025-01-02'


def test_schedule_invalid_inputs_not_silent():
    from jobs.update import schedule_ready, retry
    with pytest.raises(ValueError): schedule_ready('unknown')
    with pytest.raises(ValueError): retry(lambda: 1, attempts=0)


def test_job_snapshot_sanitizes_nan_and_date_payload(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import jobs.update as job
    import src.fundamentals as fundamentals
    path = tmp_path / 'market.db'
    monkeypatch.setattr(job, 'load_settings', lambda: SimpleNamespace(db_path=path, log_path=tmp_path/'app.log', log_level='INFO'))
    monkeypatch.setattr(job, 'ETF_UNIVERSE', {'510300':'test'})
    monkeypatch.setattr(job, 'update_quotes', lambda *a, **k: {'data':pd.DataFrame(), 'error':'offline', 'source':None})
    def val(*a, **k): return pd.DataFrame({'date':['2025-01-02'], 'pe':[10]})
    monkeypatch.setattr(fundamentals,'fetch_valuation',val)
    monkeypatch.setattr(fundamentals,'analyze_valuation',lambda *a, **k: {'date':'2025-01-02','available':False,'state':None})
    monkeypatch.setattr(fundamentals,'fetch_breadth',lambda: {'date':'2025-01-02','available':False,'state':None})
    monkeypatch.setattr(job,'build_dashboard',lambda p: {'quotes':bars(1),'market':{'state':'中性','complete':False},'value':float('nan')})
    result = job.run_update('close', force=True)
    assert result['510300']['error']
    saved = query_snapshots(path,'2020-01-01','2099-01-01')
    assert saved[-1]['payload']['value'] is None


def test_intraday_cache_ttl_does_not_suppress_after_close_update(tmp_path, monkeypatch):
    import src.market_data as market_data
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            now = datetime(2025,1,3,16,0,tzinfo=TZ)
            return now.astimezone(tz) if tz else now.replace(tzinfo=None)
    monkeypatch.setattr(market_data, 'datetime', Clock)
    path = tmp_path / 'market.db'
    save_quotes(path, '510300', bars(), 'fixture')
    with sqlite3.connect(path) as db:
        db.execute("UPDATE quotes SET fetched_at='2025-01-03T06:00:00+00:00'")
    calls = []
    def fetch(*a, **k):
        calls.append(k['provider']); return bars(end='2025-01-03')
    result = update_quotes(path, '510300', fetcher=fetch, retries=1)
    assert calls == ['eastmoney']
    assert str(result['data'].date.max().date()) == '2025-01-03'
