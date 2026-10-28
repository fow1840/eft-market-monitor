import pytest
from src.portfolio import analyze_portfolio, CATEGORIES


def sample():
    return [dict(name='宽基', amount=8000, category='核心宽基', target_pct=75),
            dict(name='现金', amount=2000, category='现金/短债', target_pct=25)]


def test_hand_calculated_and_exact_boundary():
    result = analyze_portfolio(sample())
    assert result['total_amount'] == 10000
    frame = result['holdings']
    assert frame.current_pct.tolist() == [80, 20]
    assert frame.deviation_pp.tolist() == [5, -5]
    assert not frame.rebalance_needed.any()
    assert set(result['categories'].category) == set(CATEGORIES)
    assert result['categories'].current_pct.sum() == pytest.approx(100)
    assert result['categories'].target_pct.sum() == pytest.approx(100)


def test_over_boundary_and_missing_target_holding():
    rows = sample()
    rows[0]['amount'] = 9000
    rows[1]['amount'] = 1000
    result = analyze_portfolio(rows)
    assert result['holdings'].rebalance_needed.all()
    rows[1]['amount'] = 0
    assert analyze_portfolio(rows)['holdings'].iloc[1].current_pct == 0


@pytest.mark.parametrize('field,value', [('amount', -1), ('amount', float('nan')),
    ('amount', float('inf')), ('target_pct', 101), ('target_pct', None),
    ('name', ''), ('category', '未知'), ('amount', True)])
def test_bad_inputs(field, value):
    rows = sample()
    rows[0][field] = value
    with pytest.raises(ValueError):
        analyze_portfolio(rows)


def test_empty_zero_and_wrong_target():
    with pytest.raises(ValueError):
        analyze_portfolio([])
    for rows in [[dict(name='现金', category='现金/短债', amount=0, target_pct=100)],
                 [dict(name='现金', category='现金/短债', amount=100, target_pct=99)]]:
        with pytest.raises(ValueError):
            analyze_portfolio(rows)
