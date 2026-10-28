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

from src.fundamentals import analyze_breadth, fetch_breadth


def breadth_sample():
    return pd.DataFrame({'code':['600001','300001','688001','830001','600002'], 'name':['ST测试','创业','科创','北交','普通'],
        'previous_close':[10]*5, 'close':[10.5,12,8,13,10], 'amount':[100]*5,
        'listed_sessions':[100]*5, 'ma20':[9]*5, 'ma60':[9]*5})


def test_breadth_hand_counts_board_limits_and_coverage():
    result = analyze_breadth(breadth_sample(),'2025-01-02','sample',5)
    assert result['advances'] == 3
    assert result['declines'] == 1
    assert result['unchanged'] == 1
    assert result['advance_ratio'] == .6
    assert result['turnover'] == 500
    assert result['above_ma20_ratio'] == .8
    assert result['inferred_limit_up_count'] == 3
    assert result['inferred_limit_down_count'] == 1
    assert result['limit_up_count'] is None
    assert result['state'] == '改善'


def test_breadth_incomplete_missing_suspension_and_duplicates():
    data = breadth_sample()
    data.loc[0,'close'] = None
    result = analyze_breadth(data,'2025-01-02',expected_count=6)
    assert result['state'] is None
    assert result['above_ma20_ratio'] is None
    assert result['excluded_count'] == 1
    data.loc[0,'code'] = data.loc[1,'code']
    with pytest.raises(ValueError): analyze_breadth(data,'2025-01-02')
    assert not analyze_breadth(pd.DataFrame(),'2025-01-02')['available']


def test_breadth_api_failure(monkeypatch):
    def fail(*a, **k): raise TimeoutError('offline')
    monkeypatch.setattr('src.fundamentals.requests.get', fail)
    with pytest.raises(TimeoutError): fetch_breadth()


def test_new_listing_and_published_limits():
    data = breadth_sample()
    data['listed_sessions'] = 1
    data['limit_up'] = [10.5,12,12,13,11]
    data['limit_down'] = [9.5,8,8,7,9]
    result = analyze_breadth(data,'2025-01-02',expected_count=5)
    assert result['inferred_limit_up_count'] is None
    assert result['limit_up_count'] == 3
    assert result['limit_down_count'] == 1


def test_nonfinite_and_future_data_rejected():
    data = pd.DataFrame({'date':['2025-01-01'], 'shares':[float('inf')]})
    with pytest.raises(ValueError): analyze_shares(data)
    data = breadth_sample()
    with pytest.raises(ValueError): analyze_breadth(data,'2099-01-01')


def test_shares_calendar_exact_continuity_and_missing_day():
    calendar = pd.bdate_range('2025-01-01',periods=23)
    frame = pd.DataFrame({'date':calendar[:21], 'shares':range(100,121)})
    result = analyze_shares(frame,trading_calendar=calendar)
    assert result['change20'] == pytest.approx(.2)
    assert result['change_basis'] == 'verified trading sessions'
    broken = frame.drop(index=19)
    result = analyze_shares(broken,trading_calendar=calendar)
    assert result['change1'] is None
    assert result['change5'] is None
    assert result['state'] is None
    with pytest.raises(ValueError): analyze_shares(frame,trading_calendar=calendar[1:])
