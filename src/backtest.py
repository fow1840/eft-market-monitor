"""Auditable long-only next-open research backtests, without synthetic history.

All strategies start with the SAME cash budget. Monthly DCA deploys an equal
slice of that budget each month; undeployed cash earns zero. No external flows
are introduced, so NAV returns are directly comparable. This is deliberately
not an IRR comparison between unequal contribution schedules.
Signals dated T are close-time observations and execute at T+1 open. Callers
must supply point-in-time, previously available five-dimension signals; this
module never reconstructs past valuations/shares from today's data.
"""
from dataclasses import dataclass
import numpy as np
import pandas as pd


@dataclass
class BacktestResult:
    daily: pd.DataFrame
    metrics: dict
    assumptions: str


def validate_prices(prices: pd.DataFrame) -> pd.DataFrame:
    required = {'date', 'open', 'close'}
    if not required.issubset(prices.columns) or len(prices) < 2:
        raise ValueError('At least two rows of date/open/close required')
    frame = prices.loc[:, ['date', 'open', 'close']].copy()
    frame['date'] = pd.to_datetime(frame['date'], errors='raise')
    if frame['date'].isna().any() or frame['date'].duplicated().any():
        raise ValueError('Missing or duplicate dates')
    if not frame['date'].is_monotonic_increasing:
        raise ValueError('Dates must be increasing')
    for col in ('open', 'close'):
        frame[col] = pd.to_numeric(frame[col], errors='raise')
        if not np.isfinite(frame[col]).all() or (frame[col] <= 0).any():
            raise ValueError('Prices must be positive and finite; missing data is not filled')
    return frame.reset_index(drop=True)


def performance_metrics(daily: pd.DataFrame, initial_capital: float) -> dict:
    equity = daily['equity']
    # Include starting cash in the peak and first-day fee/return measurement.
    returns = equity.div(equity.shift(1).fillna(initial_capital)).sub(1)
    nav = pd.concat([pd.Series([initial_capital]), equity], ignore_index=True)
    drawdown = nav.div(nav.cummax()).sub(1)
    years = max((daily['date'].iloc[-1] - daily['date'].iloc[0]).days / 365.25, 1 / 252)
    annual = float((equity.iloc[-1] / initial_capital) ** (1 / years) - 1)
    volatility = float(returns.std(ddof=1) * np.sqrt(252))
    max_dd = float(drawdown.min())
    annual_returns = returns.groupby(daily['date'].dt.year).apply(lambda x: float((1 + x).prod() - 1))
    return {'total_return': float(equity.iloc[-1] / initial_capital - 1),
            'annual_return': annual, 'max_drawdown': max_dd,
            'volatility': volatility,
            'sharpe': float(returns.mean() / returns.std(ddof=1) * np.sqrt(252)) if volatility > 1e-12 else None,
            'calmar': annual / abs(max_dd) if max_dd < -1e-12 else None,
            'worst_year': float(annual_returns.min()),
            'annual_returns': {int(k): v for k, v in annual_returns.items()},
            'trades': int(daily['trades'].sum()), 'fees': float(daily['fee'].sum())}


def run_backtest(prices: pd.DataFrame, strategy: str = 'hold', *,
                 signals: pd.Series | None = None, initial_capital: float = 100000,
                 fee_rate: float = .0003, dca_months: int = 12) -> BacktestResult:
    frame = validate_prices(prices)
    if strategy not in {'hold', 'dca', 'risk'}:
        raise ValueError('Unknown strategy')
    if not np.isfinite(initial_capital) or initial_capital <= 0:
        raise ValueError('Positive initial capital required')
    if not np.isfinite(fee_rate) or not 0 <= fee_rate < 1:
        raise ValueError('Fee rate must be in [0,1)')
    if not isinstance(dca_months, int) or isinstance(dca_months, bool) or dca_months < 1:
        raise ValueError('Positive integer dca_months required')
    targets = None
    if strategy == 'risk':
        if signals is None or not isinstance(signals.index, pd.DatetimeIndex):
            raise ValueError('Risk strategy requires dated point-in-time exposure signals')
        if signals.index.has_duplicates or not signals.index.is_monotonic_increasing:
            raise ValueError('Signal dates must be unique and increasing')
        if not signals.index.isin(frame['date']).all():
            raise ValueError('Signal dates must belong to supplied trading dates')
        if not np.isfinite(signals).all() or not signals.between(0, 1).all():
            raise ValueError('Exposure must be finite in [0,1]')
        # Missing close-time signal -> zero exposure on following session.
        targets = signals.reindex(pd.DatetimeIndex(frame['date'])).fillna(0).shift(1).fillna(0)
    cash, units, last_month = float(initial_capital), 0., None
    rows = []
    for i, row in frame.iterrows():
        month = row['date'].to_period('M')
        fee, trades = 0., 0
        if strategy == 'hold':
            buy_budget = cash
        elif strategy == 'dca':
            buy_budget = min(cash, initial_capital / dca_months) if month != last_month else 0.
        else:
            equity_open = cash + units * row['open']
            target_value = float(targets.iloc[i]) * equity_open
            difference = target_value - units * row['open']
            if difference < -1e-8:
                sold = min(units, -difference / row['open'])
                proceeds = sold * row['open']
                fee = proceeds * fee_rate
                units -= sold
                cash += proceeds - fee
                trades = 1
            buy_budget = min(cash, max(0., difference) * (1 + fee_rate))
        if buy_budget > 1e-8:
            cost = buy_budget / (1 + fee_rate)
            fee += buy_budget - cost
            units += cost / row['open']
            cash -= buy_budget
            trades += 1
        rows.append({'date': row['date'], 'equity': cash + units * row['close'],
                     'cash': cash, 'units': units, 'fee': fee, 'trades': trades})
        last_month = month
    daily = pd.DataFrame(rows)
    return BacktestResult(daily, performance_metrics(daily, initial_capital),
                          'Equal initial cash; zero cash yield; fractional units; next-session open execution; '
                          'fee on buys and sells; no slippage/tax/dividend reconstruction; DCA uses reserved cash.')


def compare_strategies(prices, signals=None, **kwargs):
    """Risk omitted explicitly when historical five-dimension signals unavailable."""
    results = {name: run_backtest(prices, name, **kwargs) for name in ('hold', 'dca')}
    if signals is not None:
        results['risk'] = run_backtest(prices, 'risk', signals=signals, **kwargs)
    return results


def validation_study(prices: pd.DataFrame, signals: pd.Series | None = None,
                     split_fraction: float = .7, fee_rates=(0., .0003, .001),
                     dca_months=(6, 12, 24)) -> dict:
    """Chronological holdout and parameter/cost study; never fits to holdout.

    This diagnostic does not prove strategy effectiveness or select parameters.
    Annual slices are observations, not labels inferred from future outcomes.
    Risk comparison is unavailable unless real point-in-time exposures are given.
    """
    frame = validate_prices(prices)
    if not 0 < split_fraction < 1:
        raise ValueError('Split fraction must be between zero and one')
    cut = int(len(frame) * split_fraction)
    if cut < 2 or len(frame) - cut < 2:
        raise ValueError('Each chronological partition needs at least two sessions')
    partitions = {'in_sample': frame.iloc[:cut], 'out_of_sample': frame.iloc[cut:]}
    for year, part in frame.groupby(frame.date.dt.year):
        if len(part) >= 2:
            partitions[f'year_{year}'] = part
    rows = []
    for label, part in partitions.items():
        part_signals = signals.reindex(pd.DatetimeIndex(part.date)).dropna() if signals is not None else None
        for cost in fee_rates:
            for months in dca_months:
                results = compare_strategies(part, signals=part_signals, fee_rate=cost, dca_months=months)
                for strategy, result in results.items():
                    rows.append({'partition': label, 'start': part.date.iloc[0],
                                 'end': part.date.iloc[-1], 'fee_rate': cost,
                                 'dca_months': months, 'strategy': strategy, **result.metrics})
    return {'results': pd.DataFrame(rows),
            'conclusion': '保留简单策略为基准；未完成真实五维历史、样本外与风险收益验证前，不认定复杂策略有效。',
            'limitations': ['未提供交易日历，无法自动判定停牌与缺失交易日；不插值补价。',
                            '历史上市样本与复权/分红须由数据源单独核验。',
                            '样本外仅用于诊断，不自动调参；各分段从现金重新开始。']}
