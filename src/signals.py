"""Explainable categorical market state, not investment instructions or a score."""
DIMENSIONS = ('trend', 'volume', 'shares', 'valuation', 'breadth')
LABELS = {
    'trend': {'强': 'positive', '中性': 'neutral', '弱': 'negative'},
    'volume': {'放量上涨': 'positive', '缩量上涨': 'neutral', '放量下跌': 'negative', '缩量下跌': 'negative', '平量平价': 'neutral'},
    'shares': {'流入': 'positive', '稳定': 'neutral', '流出': 'negative'},
    'valuation': {'偏低': 'positive', '中性': 'neutral', '偏高': 'negative'},
    'breadth': {'强': 'positive', '改善': 'positive', '中性': 'neutral', '偏弱': 'negative', '弱': 'negative'},
}


def market_state(dimensions: dict) -> dict:
    """Missing any dimension prevents an affirmative directional conclusion.

    Independent valuation/flow inputs corroborate, never override weak trend
    and breadth. The output exposes availability so neutral never means healthy.
    """
    unknown = set(dimensions) - set(DIMENSIONS)
    if unknown:
        raise ValueError('unknown dimensions: ' + ','.join(sorted(unknown)))
    available = {}
    missing = []
    reasons = []
    for name in DIMENSIONS:
        label = dimensions.get(name)
        if label is None or label == '数据不足' or label == '不可用':
            missing.append(name)
            reasons.append(f'{name}：数据不可用')
        elif label not in LABELS[name]:
            raise ValueError(f'invalid {name} label: {label}')
        else:
            available[name] = label
            reasons.append(f'{name}：{label}')
    state = '中性'
    if missing:
        reasons.append('五维数据不完整，暂不作方向性判断；中性不代表低风险')
    else:
        trend = available['trend']
        breadth = available['breadth']
        supporting = [LABELS[name][available[name]] for name in ('volume', 'shares', 'valuation')]
        if trend == '弱' and breadth in ('弱', '偏弱'):
            state = '弱'
        elif trend == '弱' or breadth in ('弱', '偏弱'):
            state = '偏弱'
        elif trend == '强' and breadth == '强' and supporting.count('positive') >= 2 and 'negative' not in supporting:
            state = '强'
        elif trend == '强' and breadth in ('强', '改善') and supporting.count('negative') <= 1:
            state = '改善'
        elif trend == '中性' and breadth == '改善' and supporting.count('positive') >= 2:
            state = '改善'
        elif supporting.count('negative') >= 2:
            state = '偏弱'
        reasons.append('按趋势和宽度优先、其余维度佐证的规则判定；市场状态不替代仓位限制')
    return {'state': state, 'reasons': reasons, 'available': available, 'missing': missing,
            'complete': not missing}
