import numpy as np
import pandas as pd
import pytest
from src.backtest import run_backtest, compare_strategies


def prices(n=10):
    return pd.DataFrame({'date': pd.bdate_range('2020-01-01', periods=n), 'open': 10., 'close': 10.})


def test_hold_hand_calculation_fee():
    p = prices(2)
    p.loc[1, ['open', 'close']] = 12
    result = run_backtest(p, initial_capital=100, fee_rate=.01)
    assert result.daily.iloc[-1].equity == pytest.approx(100 / 1.01 * 1.2)
    assert result.metrics['trades'] == 1
    assert result.metrics['fees'] == pytest.approx(100 - 100 / 1.01)


def test_signal_not_used_same_day_or_future():
    p = prices(4)
    p.loc[1, ['open', 'close']] = [10, 20]
    p.loc[2, ['open', 'close']] = [20, 10]
    s = pd.Series([0., 1., 0., 0.], index=pd.DatetimeIndex(p.date))
    result = run_backtest(p, 'risk', signals=s, fee_rate=0)
    assert result.daily.iloc[1].units == 0
    assert result.daily.iloc[2].equity == pytest.approx(50000)
    changed = s.copy(); changed.iloc[-1] = 1
    pd.testing.assert_frame_equal(result.daily, run_backtest(p, 'risk', signals=changed, fee_rate=0).daily)


def test_missing_signals_safe_cash():
    p = prices()
    s = pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    assert run_backtest(p, 'risk', signals=s).metrics['trades'] == 0


def test_dca_reserved_cash_comparable_and_constant_prices():
    p = prices(70)
    r = compare_strategies(p, initial_capital=1200, dca_months=12, fee_rate=0)
    assert r['hold'].daily.iloc[0].cash == 0
    assert r['dca'].daily.iloc[0].cash == 1100
    for result in r.values():
        assert (result.daily.equity == 1200).all()
        assert result.metrics['total_return'] == 0
        assert result.metrics['sharpe'] is None
    assert 'risk' not in r


@pytest.mark.parametrize('bad', [np.nan, 0, -1, np.inf])
def test_bad_prices_rejected(bad):
    p = prices(); p.loc[2, 'close'] = bad
    with pytest.raises(ValueError): run_backtest(p)


def test_duplicate_and_unsorted_dates():
    p = prices(); p.loc[1, 'date'] = p.loc[0, 'date']
    with pytest.raises(ValueError): run_backtest(p)
    with pytest.raises(ValueError): run_backtest(prices().iloc[::-1])


def test_cost_effect_and_drawdown_from_initial_cash():
    r = run_backtest(prices(), fee_rate=.01)
    assert r.metrics['max_drawdown'] == pytest.approx(-.01 / 1.01)
    assert r.metrics['total_return'] < run_backtest(prices(), fee_rate=0).metrics['total_return']


def test_risk_requires_history():
    with pytest.raises(ValueError): run_backtest(prices(), 'risk')
