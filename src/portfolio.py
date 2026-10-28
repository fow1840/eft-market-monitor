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
