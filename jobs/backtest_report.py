"""Read-only cached-price research report: python -m jobs.backtest_report.

No network requests and no writes to the SQLite source. No historical signals
are invented when real point-in-time five-dimension inputs are unavailable.
"""
from __future__ import annotations
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
from config import load_settings
from src.backtest import compare_strategies, validation_study, validate_prices


def read_cached_prices(db_path: Path, symbol='510300') -> pd.DataFrame:
    path = Path(db_path).resolve()
    if not path.is_file():
        raise ValueError('Cached database does not exist; run quote update first')
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
        frame = pd.read_sql_query('SELECT date,open,close,source,fetched_at FROM quotes WHERE symbol=? ORDER BY date',
                                  db, params=(symbol,))
    if frame.empty:
        raise ValueError('No cached quotes for symbol')
    return frame


def build_report(cached: pd.DataFrame, *, start='2018-01-01', end=None,
                 calendar: pd.DataFrame | None = None) -> dict:
    data = cached.copy()
    data['date'] = pd.to_datetime(data['date'], errors='raise')
    # Today's cached bar may be intraday: exclude it even if caller requests it.
    today = pd.Timestamp(datetime.now(ZoneInfo('Asia/Shanghai')).date())
    upper = min(pd.Timestamp(end) if end else today - pd.Timedelta(days=1), today - pd.Timedelta(days=1))
    data = data.loc[data.date.between(pd.Timestamp(start), upper)].reset_index(drop=True)
    prices = validate_prices(data)
    dates = pd.DatetimeIndex(prices.date)
    if (dates.dayofweek >= 5).any():
        raise ValueError('Weekend dates in daily exchange quotes')
    weekdays = pd.bdate_range(dates.min(), dates.max())
    calendar_validation = {'status': '未验证',
                           'weekday_gaps_including_holidays': len(weekdays.difference(dates)),
                           'missing_exchange_sessions': None,
                           'note': '未提供独立官方交易日历；工作日空档包含节假日，不等于缺失交易日，不能宣称交易日覆盖完整。'}
    if calendar is not None:
        expected = pd.DatetimeIndex(pd.to_datetime(calendar['date'], errors='raise')).normalize()
        if expected.has_duplicates or expected.isna().any():
            raise ValueError('Invalid calendar')
        expected = expected[(expected >= dates.min()) & (expected <= dates.max())]
        missing, unexpected = expected.difference(dates), dates.difference(expected)
        calendar_validation = {'status': '通过' if not len(missing) and not len(unexpected) else '不通过',
                               'missing_exchange_sessions': missing.strftime('%Y-%m-%d').tolist(),
                               'unexpected_sessions': unexpected.strftime('%Y-%m-%d').tolist(),
                               'note': '根据调用方提供的交易日历比较；日历来源真实性需另行核验。'}
        if len(missing) or len(unexpected):
            raise ValueError('Cached quotes do not match provided trading calendar')
    baseline = compare_strategies(prices, fee_rate=.0003, dca_months=12)
    study = validation_study(prices)
    digest = hashlib.sha256(prices.to_csv(index=False, float_format='%.10g').encode()).hexdigest()
    return {'symbol': '510300', 'requested_start': start, 'start': str(dates.min().date()),
            'end': str(dates.max().date()), 'rows': len(prices),
            'sources': sorted(data.source.dropna().unique().tolist()),
            'fetched_at': sorted(data.fetched_at.dropna().unique().tolist()),
            'price_sha256': digest, 'calendar_validation': calendar_validation,
            'validation': {'duplicates': int(dates.duplicated().sum()), 'missing_values': int(prices.isna().sum().sum()),
                           'positive_finite_prices': True, 'increasing_dates': True,
                           'max_absolute_close_return': float(prices.close.pct_change().abs().max()),
                           'same_day_bar_excluded': True},
            'metrics': {name: result.metrics for name, result in baseline.items()},
            'sensitivity': study['results'].to_dict(orient='records'),
            'conclusion': study['conclusion'],
            'risk_strategy': '不可用：没有真实、可验证的历史五维时点信号，未用趋势替代五维。',
            'assumptions': baseline['hold'].assumptions,
            'limitations': study['limitations'] + [
                '510300为ETF价格代理，并非沪深300指数本身；未复权价格未加回分红，不能称为总收益。',
                '初始资金100000；月定投以同等初始预算分12个月投入，剩余现金零收益，不是外部月度新增资金的IRR。',
                '基准手续费单边0.03%；未计滑点、最低佣金、整数份额限制及其他个别账户费用。',
                '净值以每日收盘计量，不表示盘中风险；分段测试重新从现金开始，年化短期结果可能不稳定。',
                '公开行情为单一来源缓存，本报告不等于独立数据源对账；2018起始日期之前不评价。']}


def _percent(value):
    return '不适用' if value is None else f'{value * 100:.2f}%'


def _ratio(value):
    return '不适用' if value is None else f'{value:.3f}'


def render_markdown(report: dict) -> str:
    lines = ['# 510300 真实缓存价格回测报告', '',
             f"样本：{report['start']}—{report['end']}，{report['rows']} 条记录。来源：{', '.join(report['sources'])}（AKShare 接口）。",
             '', '**以下为未复权 ETF 价格研究结果，不是含分红总收益，也不是收益承诺。**', '',
             '## 基准比较', '',
             '相同初始资金100000元，手续费单边0.03%。月定投从现有资金中每月投入1/12，不添加外部资金。', '',
             '| 策略 | 区间收益 | 年化 | 最大回撤 | 波动率 | 夏普 | 卡玛 | 最差年度 | 次数 | 费用元 |',
             '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for name, metric in report['metrics'].items():
        label = {'hold': '买入持有', 'dca': '固定月度分批投入'}[name]
        values = [label, *[_percent(metric[k]) for k in ('total_return', 'annual_return', 'max_drawdown', 'volatility')],
                  _ratio(metric['sharpe']), _ratio(metric['calmar']), _percent(metric['worst_year']),
                  str(metric['trades']), f"{metric['fees']:.2f}"]
        lines.append('| ' + ' | '.join(values) + ' |')
    lines += ['', report['risk_strategy'], '', '夏普采用零无风险利率与252交易日标准差；年度结果为样本内该自然年的复合收益，首尾年份可能不完整。', '',
              '## 样本外、费用与参数检查', '',
              '按时间前70%/后30%分割，不自动选择最优参数；另逐自然年分段。费用0/0.03%/0.1%，月度分批期限6/12/24个月。', '',
              '| 分段 | 策略 | 期限月 | 费用率 | 起始 | 截止 | 年化 | 最大回撤 | 夏普 |',
              '|---|---|---:|---:|---|---|---:|---:|---:|']
    for row in report['sensitivity']:
        if row['partition'] not in {'in_sample', 'out_of_sample'}:
            continue
        lines.append('| ' + ' | '.join([row['partition'], row['strategy'], str(row['dca_months']),
            _percent(row['fee_rate']), str(pd.Timestamp(row['start']).date()), str(pd.Timestamp(row['end']).date()),
            _percent(row['annual_return']), _percent(row['max_drawdown']), _ratio(row['sharpe'])]) + ' |')
    lines += ['', '逐年度分段明细见同目录 BACKTEST_REPORT.json。持有策略不受定投期限参数影响，重复项用于统一比较网格。', '',
              report['conclusion'], '', '## 数据检查与覆盖限制', '',
              f"- 日期唯一递增、价格正且有限，无空值；当前上海日期的未完成K线已排除。",
              f"- 最大单日收盘绝对变化：{_percent(report['validation']['max_absolute_close_return'])}。",
              f"- 交易日历验证：{report['calendar_validation']['status']}。{report['calendar_validation'].get('note', '')}",
              f"- 价格内容 SHA256：`{report['price_sha256']}`。", '', '## 假设与已知限制', '']
    lines.extend('- ' + value for value in report['limitations'])
    lines += ['', '执行时点：T日收盘信号最早T+1开盘执行；本次没有历史五维信号，因此只运行不依赖信号的两种基准。', '',
              '复现：`python -m jobs.backtest_report`。只读本地 SQLite 缓存；不访问网络，不更改数据库。']
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=load_settings().db_path)
    parser.add_argument('--output', type=Path, default=Path('docs'))
    parser.add_argument('--start', default='2018-01-01')
    parser.add_argument('--end')
    parser.add_argument('--calendar', type=Path, help='Optional exchange-calendar CSV with date column')
    args = parser.parse_args()
    report = build_report(read_cached_prices(args.db), start=args.start, end=args.end,
                          calendar=pd.read_csv(args.calendar) if args.calendar else None)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'BACKTEST_REPORT.md').write_text(render_markdown(report), encoding='utf-8')
    def serialize(value):
        if isinstance(value, (pd.Timestamp, datetime)):
            return value.isoformat()
        if isinstance(value, np.generic):
            return value.item()
        raise TypeError(f'Cannot serialize {type(value)}')
    (args.output / 'BACKTEST_REPORT.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=serialize, allow_nan=False), encoding='utf-8')
    print(f"Read-only report written: {args.output}; {report['rows']} rows {report['start']}..{report['end']}")


if __name__ == '__main__':
    main()
