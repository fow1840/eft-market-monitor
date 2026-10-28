import numpy as np
import pandas as pd
import pytest
from src.indicators import calculate_indicators, summarize_indicators


def sample(n=80):
    return pd.DataFrame({'date': pd.bdate_range('2020-01-01', periods=n), 'close': range(1,n+1), 'volume': [100]*n})


def test_hand_calculation():
    result = calculate_indicators(sample())
    assert result.iloc[4].ma5 == 3  # (1+2+3+4+5)/5
    last = result.iloc[-1]
    assert last.ma20 == 70.5
    assert last.ma60 == 50.5
    assert last.return20 == pytest.approx(80/60-1)
    assert last.return60 == pytest.approx(80/20-1)
    assert last.drawdown60 == 0
    assert last.volume_ratio == 1
    assert last.trend == '强'
    assert last.volume_state == '放量上涨'


def test_decline_and_drawdown():
    frame = sample()
    frame['close'] = list(range(80,0,-1))
    last = calculate_indicators(frame).iloc[-1]
    assert last.drawdown60 == pytest.approx(1/60-1)
    assert last.trend == '弱'
    assert last.volume_state == '放量下跌'


def test_no_future_contamination():
    frame = sample()
    prefix = calculate_indicators(frame.iloc[:65])
    frame.loc[65:, 'close'] = 1_000_000
    pd.testing.assert_frame_equal(prefix, calculate_indicators(frame).iloc[:65])


def test_missing_not_filled_and_short_history():
    frame = sample()
    frame.loc[70, 'close'] = np.nan
    result = calculate_indicators(frame)
    assert pd.isna(result.iloc[70].return20)
    assert pd.isna(result.iloc[-1].ma20)
    assert result.iloc[-1].trend == '数据不足'
    assert calculate_indicators(sample(4)).ma5.isna().all()


def test_zero_volume_and_flat():
    frame = sample()
    frame['volume'] = 0
    frame['close'] = 5
    result = calculate_indicators(frame)
    assert result.volume_ratio.isna().all()
    frame['volume'] = 100
    assert calculate_indicators(frame).iloc[-1].volume_state == '平量平价'


@pytest.mark.parametrize('value', [-1, np.inf, 0])
def test_bad_price(value):
    frame = sample(); frame['close'] = frame['close'].astype(float); frame.loc[10, 'close'] = value
    with pytest.raises(ValueError): calculate_indicators(frame)


def test_duplicate_or_reversed_date():
    frame = sample()
    with pytest.raises(ValueError): calculate_indicators(frame.iloc[::-1])
    frame.loc[1, 'date'] = frame.loc[0, 'date']
    with pytest.raises(ValueError): calculate_indicators(frame)


def test_empty():
    assert summarize_indicators(sample(0))['trend'] == '数据不足'
