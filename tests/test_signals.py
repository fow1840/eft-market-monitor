import pytest
from src.signals import market_state


def dimensions(trend='中性', breadth='中性', volume='平量平价', shares='稳定', valuation='中性'):
    return dict(trend=trend, breadth=breadth, volume=volume, shares=shares, valuation=valuation)


@pytest.mark.parametrize('values,expected', [
    (dimensions('强','强','放量上涨','流入','偏低'),'强'),
    (dimensions('强','强','放量上涨','流入'),'强'),
    (dimensions('强','强','放量上涨','稳定','偏低'),'强'),
    (dimensions('强','强','缩量上涨','流入','偏低'),'强'),
    (dimensions('强','强'),'改善'),
    (dimensions('强','改善'),'改善'),
    (dimensions('中性','改善','放量上涨','流入'),'改善'),
    (dimensions('中性','改善','放量上涨','稳定','偏低'),'改善'),
    (dimensions('弱','弱'),'弱'),
    (dimensions('弱','偏弱'),'弱'),
    (dimensions('弱','强','放量上涨','流入','偏低'),'偏弱'),
    (dimensions('强','弱','放量上涨','流入','偏低'),'偏弱'),
    (dimensions('中性','弱'),'偏弱'),
    (dimensions('中性','偏弱'),'偏弱'),
    (dimensions('中性','强','放量下跌','流出'),'偏弱'),
    (dimensions('强','中性','缩量下跌','流出'),'偏弱'),
    (dimensions(),'中性'),
    (dimensions('中性','强'),'中性'),
    (dimensions('强','中性'),'中性'),
    (dimensions('中性','改善'),'中性'),
    (dimensions('强','改善','放量下跌','流出'),'偏弱'),
    (dimensions('中性','中性','放量上涨','流入','偏低'),'中性'),
])
def test_scenarios(values, expected):
    result = market_state(values)
    assert result['state'] == expected
    assert result['complete']
    assert len(result['reasons']) >= 5
    assert 'score' not in result


@pytest.mark.parametrize('name', ['trend','volume','shares','valuation','breadth'])
def test_missing_prevents_false_positive(name):
    values = dimensions('强','强','放量上涨','流入','偏低')
    values[name] = None
    result = market_state(values)
    assert result['state'] == '中性'
    assert result['missing'] == [name]
    assert not result['complete']
    assert '不代表低风险' in result['reasons'][-1]


def test_unknown_and_invalid_rejected():
    with pytest.raises(ValueError): market_state({'trend':'买入'})
    with pytest.raises(ValueError): market_state({'future':'强'})


def test_no_data_safe():
    result = market_state({})
    assert len(result['missing']) == 5
    assert result['state'] == '中性'
