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
