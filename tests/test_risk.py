import pytest
from src.portfolio import risk_advice, ACTIONS, MARKET_STATES


@pytest.mark.parametrize('state', MARKET_STATES)
def test_overweight_overrides_every_market_signal(state):
    result = risk_advice(15, 5, state)
    assert result['action'] == '建议再平衡'
    assert not result['allow_extra_buy']
    assert '禁止继续加仓' in result['reason']


def test_threshold_and_small_overweight():
    assert risk_advice(10, 5, '强')['action'] == '暂缓额外买入'
    assert risk_advice(5.01, 5, '强')['action'] == '暂缓额外买入'
    assert risk_advice(5, 10, '强')['action'] == '正常定投'
    assert risk_advice(4.99, 10, '强')['action'] == '可小额补目标仓位'


@pytest.mark.parametrize('state', ['弱', '偏弱', '数据不足'])
def test_missing_or_weak_data_cannot_trigger_extra_buy(state):
    result = risk_advice(0, 20, state)
    assert result['action'] == '暂缓额外买入'
    assert not result['allow_extra_buy']


def test_at_target_and_zero_target():
    assert risk_advice(10, 10, '强')['action'] == '保持'
    assert risk_advice(0, 0, '强')['action'] == '保持'


@pytest.mark.parametrize('current,target,state', [(float('nan'), 5, '强'),
    (101, 5, '强'), (5, -1, '弱'), (5, 5, '未知')])
def test_invalid_inputs(current, target, state):
    with pytest.raises(ValueError):
        risk_advice(current, target, state)


def test_every_output_is_allowed():
    for current in [0, 5, 10, 20, 100]:
        for target in [0, 5, 10, 20, 100]:
            for state in MARKET_STATES:
                result = risk_advice(current, target, state)
                assert result['action'] in ACTIONS
                assert result['reason']
