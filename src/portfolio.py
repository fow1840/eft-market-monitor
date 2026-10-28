"""Local portfolio arithmetic. Percentages and deviations use percentage points."""
from math import isfinite
from typing import Iterable, Mapping

import pandas as pd

CATEGORIES = ('核心宽基', '海外', '科技', '医药', '黄金', '现金/短债')


def _number(value, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f'{name} 必须是有限数值')
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{name} 必须是有限数值') from None
    if not isfinite(result):
        raise ValueError(f'{name} 必须是有限数值')
    return result


def analyze_portfolio(rows: Iterable[Mapping], threshold_pp: float = 5) -> dict:
    """Validate a complete portfolio and derive weights; never trust input weights.

    Each row has name, amount (yuan), category, target_pct (0..100).
    Include cash as a holding. Targets must total 100%; no silent normalization.
    Zero amounts are allowed to represent a target allocation not yet held.
    """
    threshold = _number(threshold_pp, '偏离阈值')
    if not 0 <= threshold <= 100:
        raise ValueError('偏离阈值必须在 0 到 100 之间')
    clean = []
    for row in rows:
        name = str(row.get('name', '')).strip()
        category = row.get('category')
        amount = _number(row.get('amount'), '金额')
        target = _number(row.get('target_pct'), '目标仓位')
        if not name or category not in CATEGORIES:
            raise ValueError('请填写名称并使用支持的资产分类')
        if amount < 0 or not 0 <= target <= 100:
            raise ValueError('金额不可为负，目标仓位必须在 0 到 100 之间')
        clean.append(dict(name=name, category=category, amount=amount, target_pct=target))
    if not clean:
        raise ValueError('请至少输入一项资产')
    holdings = pd.DataFrame(clean)
    total = float(holdings.amount.sum())
    if not isfinite(total) or total <= 0:
        raise ValueError('总金额必须大于零且有限')
    if abs(float(holdings.target_pct.sum()) - 100) > 1e-6:
        raise ValueError('目标仓位合计必须为 100%')
    def derive(frame):
        frame['current_pct'] = frame.amount / total * 100
        frame['deviation_pp'] = frame.current_pct - frame.target_pct
        frame['rebalance_needed'] = frame.deviation_pp.abs() > threshold + 1e-9
        return frame
    categories = holdings.groupby('category')[['amount', 'target_pct']].sum().reindex(CATEGORIES, fill_value=0).reset_index()
    return dict(total_amount=total, holdings=derive(holdings), categories=derive(categories))


MARKET_STATES = ('强', '改善', '中性', '偏弱', '弱', '数据不足')
ACTIONS = ('保持', '正常定投', '暂缓额外买入', '可小额补目标仓位', '建议再平衡')


def risk_advice(current_pct: float, target_pct: float, market_state: str,
                threshold_pp: float = 5) -> dict:
    """Allocation rules take precedence over market signals; no orders are sent.

    `allow_extra_buy` refers to discretionary extra purchases, not a trade order.
    Any overweight blocks extra buying, including inside the rebalance band.
    """
    current = _number(current_pct, '当前仓位')
    target = _number(target_pct, '目标仓位')
    threshold = _number(threshold_pp, '偏离阈值')
    if not all(0 <= value <= 100 for value in (current, target, threshold)):
        raise ValueError('仓位和阈值必须在 0 到 100 之间')
    if market_state not in MARKET_STATES:
        raise ValueError('未知市场状态')
    deviation = current - target
    if deviation > threshold + 1e-9:
        action, reason, allowed = '建议再平衡', '仓位超过目标且偏离超过阈值，禁止继续加仓。', False
    elif deviation > 1e-9:
        action, reason, allowed = '暂缓额外买入', '当前已超过目标仓位，暂缓额外买入。', False
    elif target == 0:
        action, reason, allowed = '保持', '目标仓位为零，保持当前配置。', False
    elif market_state == '数据不足':
        action, reason, allowed = '暂缓额外买入', '市场数据不足，无法确认市场状态。', False
    elif market_state in ('偏弱', '弱'):
        action, reason, allowed = '暂缓额外买入', '市场偏弱，先遵守风险限制。', False
    elif deviation < -threshold - 1e-9:
        action, reason, allowed = '可小额补目标仓位', '低于目标且偏离超过阈值，可分次小额补至目标范围。', True
    elif deviation < -1e-9:
        action, reason, allowed = '正常定投', '尚低于目标，按原定计划执行并限制在目标范围内。', False
    else:
        action, reason, allowed = '保持', '当前仓位符合目标配置。', False
    return dict(action=action, reason=reason, allow_extra_buy=allowed,
                deviation_pp=deviation)
