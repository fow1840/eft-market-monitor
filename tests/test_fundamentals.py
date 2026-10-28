import pandas as pd
import pytest
from src.fundamentals import analyze_shares, fetch_shares


def test_shares_hand_calculation_and_units():
    frame = pd.DataFrame({'date':pd.bdate_range('2025-01-01', periods=21), 'shares':range(100,121)})
    result = analyze_shares(frame, 'test', '万份')
    assert result['shares'] == 1_200_000
    assert result['change1'] == pytest.approx(120/119-1)
    assert result['change5'] == pytest.approx(120/115-1)
    assert result['change20'] == pytest.approx(.2)
    assert result['state'] == '流入'


def test_shares_missing_jump_duplicate():
    assert not analyze_shares(pd.DataFrame())['available']
    frame = pd.DataFrame({'date':['2025-01-01','2025-01-02'], 'shares':[100,1000]})
    assert not analyze_shares(frame)['available']
    frame['date'] = '2025-01-01'
    with pytest.raises(ValueError): analyze_shares(frame)


def test_shares_provider_failure(monkeypatch):
    def fail(*a, **k): raise TimeoutError('offline')
    monkeypatch.setattr('src.fundamentals.requests.get', fail)
    with pytest.raises(TimeoutError): fetch_shares('510300','2025-01-02')
    with pytest.raises(ValueError): fetch_shares('159915','2025-01-02')

from src.fundamentals import analyze_valuation, fetch_valuation


def test_valuation_known_percentile_and_no_pb_fabrication():
    frame = pd.DataFrame({'date':pd.bdate_range('2024-01-01', periods=250), 'pe':range(1,251), 'pb':[None]*250, 'dividend_yield':[2.0]*250})
    result = analyze_valuation(frame, 'official sample')
    assert result['pe_percentile'] == 1
    assert result['pb'] is None
    assert result['state'] == '偏高'
    assert result['source'] == 'official sample'
    assert result['dividend_yield'] == 2


def test_valuation_no_history_no_signal_and_api_failure(monkeypatch):
    assert not analyze_valuation(pd.DataFrame())['available']
    frame = pd.DataFrame({'date':['2025-01-01'], 'pe':[10], 'pb':[1], 'dividend_yield':[2]})
    assert analyze_valuation(frame)['state'] is None
    def fail(*a, **k): raise TimeoutError('offline')
    monkeypatch.setattr('src.fundamentals.requests.get', fail)
    with pytest.raises(TimeoutError): fetch_valuation('沪深300')
    with pytest.raises(ValueError): fetch_valuation('unknown')
