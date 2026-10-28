import multiprocessing as mp
import time
import pandas as pd
import pytest
from src import valuation_fallback as module


def payload(n=260):
    dates = pd.date_range('2003-01-31', periods=n, freq='ME').strftime('%Y-%m-%d').tolist()
    return {'data': {'pe': [{'日期': day, '滚动市盈率': i+1, '等权滚动市盈率': 9999} for i,day in enumerate(dates)],
                     'pb': [{'日期': day, '市净率': (i+1)/100, '等权市净率': 9999} for i,day in enumerate(dates)]},
            'errors': []}


def test_no_index_substitution_or_fetch_for_unsupported(monkeypatch):
    def forbidden(*args): raise AssertionError('must not fetch unsupported symbols')
    monkeypatch.setattr(module, '_bounded_fetch', forbidden)
    for name in ['A500','科创50','创业板','399006','unknown']:
        result = module.fetch_valuation_fallback(name)
        assert not result['available'] and result['state'] is None


def test_monthly_observations_explicit_and_correct_fields(monkeypatch):
    data = payload()
    monkeypatch.setattr(module, '_bounded_fetch', lambda timeout: data)
    result = module.fetch_valuation_fallback('沪深300', as_of='2024-08-31')
    assert result['available']
    assert result['pe'] == 260
    assert result['pb'] == 2.6
    assert result['pe_percentile'] == 1
    assert result['state'] == '偏高'
    assert result['dividend_yield'] is None
    assert '月度' in result['history_frequency']
    assert result['fields']['pe']['definition'].endswith('addTtmPe）')
    assert result['fields']['pb']['definition'].endswith('addPb）')


def test_field_date_mismatch_not_silently_filled(monkeypatch):
    data = payload(); data['data']['pb'].pop()
    monkeypatch.setattr(module, '_bounded_fetch', lambda timeout: data)
    result = module.fetch_valuation_fallback('000300', as_of='2024-08-31')
    assert result['pe'] == 260 and result['pb'] is None
    assert result['fields']['pb']['value'] == 2.59
    assert result['fields']['pb']['date'] != result['date']


def test_invalid_latest_no_fallback_to_old_value(monkeypatch):
    data = payload(); data['data']['pe'][-1]['滚动市盈率'] = None
    monkeypatch.setattr(module, '_bounded_fetch', lambda timeout: data)
    result = module.fetch_valuation_fallback('沪深300', as_of='2024-08-31')
    assert result['pe'] is None and result['pb'] is not None


def test_insufficient_history_no_state(monkeypatch):
    data = payload(20)
    monkeypatch.setattr(module, '_bounded_fetch', lambda timeout: data)
    result = module.fetch_valuation_fallback('沪深300', as_of='2004-09-30')
    assert result['pe_percentile'] is None and result['state'] is None


def test_future_and_duplicate_dates_rejected():
    for dates in [['2020-01-01','2020-01-01'], ['2099-01-01']]:
        with pytest.raises(ValueError):
            module._field_history([{'日期': d, '市净率': 1} for d in dates], 'pb', pd.Timestamp('2025-01-01'))


def test_stale_history_no_current_state(monkeypatch):
    monkeypatch.setattr(module, '_bounded_fetch', lambda timeout: payload())
    result = module.fetch_valuation_fallback('沪深300', as_of='2025-01-01')
    assert result['stale'] and result['state'] is None


def _never_returns(queue):
    time.sleep(10)


def test_deadline_terminates_child_process():
    children = {child.pid for child in mp.active_children()}
    start = time.monotonic()
    with pytest.raises(TimeoutError): module._bounded_fetch(.05, worker=_never_returns)
    assert time.monotonic() - start < 5
    assert not ({child.pid for child in mp.active_children()} - children)


def test_timeout_degrades_instead_of_crashing(monkeypatch):
    def fail(timeout): raise TimeoutError('upstream')
    monkeypatch.setattr(module, '_bounded_fetch', fail)
    result = module.fetch_valuation_fallback('沪深300')
    assert not result['available']
    assert 'TimeoutError' in result['reasons'][0]
