"""Auditable strategy comparisons from local public prices; no live calls or LLM.

Run ``python -m jobs.strategy_report`` after populating the quote cache. Missing
point-in-time fundamentals remain unavailable, never current-value backfilled.
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
from src.backtest import run_backtest, BacktestResult, performance_metrics, validate_prices

NAMES = {'A':'A 长期价值配置','B':'B 纯趋势','C':'C 价值＋趋势','D':'D 卫星仓波段'}
CAPITAL = 100000.0


def additional_metrics(daily: pd.DataFrame, initial_capital=CAPITAL) -> dict:
    """Loss period means underwater trading sessions, including unfinished runs.

    A separate strictly negative daily-return streak avoids ambiguous wording.
    """
    equity = pd.to_numeric(daily['equity'], errors='raise')
    if equity.empty or not np.isfinite(equity).all() or (equity <= 0).any():
        raise ValueError('positive finite equity required')
    returns = equity.div(equity.shift(1).fillna(initial_capital)).sub(1)
    peak = equity.cummax().clip(lower=initial_capital)
    def longest(mask):
        current = maximum = 0
        for value in mask:
            current = current+1 if value else 0
            maximum = max(maximum,current)
        return maximum
    yearly = returns.groupby(pd.to_datetime(daily['date']).dt.year).apply(lambda x:float((1+x).prod()-1))
    return {'max_underwater_sessions':longest(equity < peak-1e-8),
            'max_losing_streak_sessions':longest(returns < -1e-12),
            'annual_return_dispersion':float(yearly.std(ddof=0)),
            'positive_year_fraction':float((yearly>0).mean())}



def allocation_reference(data, weight, *, initial_capital=CAPITAL, fee_rate=.0003, rebalance=False):
    """Initial buy-and-hold or daily constant mix; zero-volume bars never fill.

    Constant mix first submits a close signal then trades the following open.
    A passive initial buy is predefined and may execute at the first tradable open.
    """
    if not 0<weight<=1 or not 0<=fee_rate<1 or initial_capital<=0:
        raise ValueError('invalid passive allocation/capital/cost')
    frame=validate_prices(data)
    volume=pd.to_numeric(data['volume'],errors='raise').reset_index(drop=True) if 'volume' in data else pd.Series(1.,index=frame.index)
    if not np.isfinite(volume).all() or (volume<0).any():raise ValueError('invalid reference volume')
    cash=float(initial_capital);units=0.;entered=False;rows=[]
    for i,row in frame.iterrows():
        fee=0.;trades=0
        tradable=volume.iloc[i]>0
        if tradable and ((rebalance and i>0) or (not rebalance and not entered)):
            equity_open=cash+units*row.open
            target=equity_open*weight
            difference=target-units*row.open
            if difference < -1e-8:
                sold=min(units,-difference/row.open);proceeds=sold*row.open
                fee=proceeds*fee_rate;units-=sold;cash+=proceeds-fee;trades=1
            elif difference > 1e-8:
                # Reserve cost inside the initial allocation budget. Subsequent
                # constant-mix rebalances target pre-fee exposure, like strategies.
                budget=min(cash,difference*(1+fee_rate) if rebalance else initial_capital*weight)
                notional=budget/(1+fee_rate);fee=budget-notional
                units+=notional/row.open;cash-=budget;trades=1
            entered=True
        rows.append(dict(date=row.date,equity=cash+units*row.close,cash=cash,units=units,fee=fee,trades=trades))
    daily=pd.DataFrame(rows)
    return BacktestResult(daily,performance_metrics(daily,initial_capital),
        'Initial allocation or next-open constant mix; zero-volume executions skipped; residual cash zero yield; no dividends.')


def passive_sleeve(data, weight, *, initial_capital=CAPITAL, fee_rate=.0003):
    return allocation_reference(data,weight,initial_capital=initial_capital,fee_rate=fee_rate)


def load_public_data(db_path) -> tuple[dict[str,pd.DataFrame],pd.DataFrame]:
    path = Path(db_path).resolve()
    if not path.is_file():
        raise ValueError('本地数据库不存在，请先更新行情')
    datasets = {}
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
        for symbol in ('510300','159665','159992'):
            data = pd.read_sql_query('SELECT date,open,high,low,close,volume,source FROM quotes WHERE symbol=? ORDER BY date',db,params=(symbol,))
            if not data.empty:datasets[symbol]=data
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='index_quotes'").fetchone()
        index = pd.read_sql_query('SELECT date,open,close,volume,source FROM index_quotes WHERE name=? ORDER BY date',db,params=('沪深300',)) if exists else pd.DataFrame()
    return datasets,index


def _closed_prices(data, end=None):
    if data.empty:return data.copy()
    data=data.copy();data['date']=pd.to_datetime(data['date'],errors='raise')
    now=datetime.now(ZoneInfo('Asia/Shanghai'))
    cutoff=pd.Timestamp(now.date()) if (now.hour,now.minute)>=(15,30) else pd.Timestamp(now.date())-pd.Timedelta(days=1)
    upper=min(pd.Timestamp(end),cutoff) if end else cutoff
    return data[data.date<=upper].reset_index(drop=True)


def _scalar(value):
    if isinstance(value,(np.integer,np.floating)):value=value.item()
    if isinstance(value,(datetime,pd.Timestamp)):return value.isoformat()
    return value


def build_comparison(datasets, *, index_prices=None, start='2015-01-01', end=None, config=None,
                     fee_rate=.0003, initial_capital=CAPITAL, dca_months=12):
    from src.strategies import run_strategy_backtest
    if not 0<=fee_rate<1:raise ValueError('invalid fee_rate')
    if initial_capital<=0:raise ValueError('invalid initial capital')
    start=pd.Timestamp(start)
    if end and pd.Timestamp(end)<start:raise ValueError('end before start')
    rows=[];curves={};decision_rows=[];stability=[];coverage={}
    main=_closed_prices(datasets.get('510300',pd.DataFrame()),end)
    if main.empty:raise ValueError('缺少510300历史行情，不能生成策略比较')
    available_main=main[main.date>=start].reset_index(drop=True)
    if len(available_main)<2:raise ValueError('回测区间行情不足')
    def add(name,symbol,group,data,runner,*,metadata=None):
        result=runner(data,fee_rate)
        nofee=runner(data,0.)
        daily=result.daily.copy()
        metrics={**result.metrics,**additional_metrics(daily,initial_capital)}
        impact=float((nofee.daily.equity.iloc[-1]-daily.equity.iloc[-1])/initial_capital*100)
        rows.append(dict(name=name,symbol=symbol,group=group,status='可计算',reason='',
                         start=str(pd.to_datetime(daily.date).min().date()),end=str(pd.to_datetime(daily.date).max().date()),
                         sessions=len(daily),fee_impact_return_pp=impact,**metrics,**(metadata or {})))
        daily['nav']=daily.equity/initial_capital
        daily['drawdown']=daily.equity/daily.equity.cummax().clip(lower=initial_capital)-1
        curves[name]=daily
        decisions=getattr(result,'decisions',None)
        if isinstance(decisions,pd.DataFrame) and not decisions.empty:
            decisions=decisions.copy();decisions['strategy']=name;decisions['symbol']=symbol
            decision_rows.extend(decisions.to_dict('records'))
        # Chronological diagnostic: reset cash each partition; full price warmup
        # before each start remains available to the rule engine, never future rows.
        full=_closed_prices(data,end)
        eligible=full[full.date>=start]
        if len(eligible)>=20:
            split=int(len(eligible)*.7)
            pieces={'前70%':eligible.iloc[:split], '后30%':eligible.iloc[split:]}
            pieces.update({str(year):part for year,part in eligible.groupby(eligible.date.dt.year) if len(part)>=2})
            for label,part in pieces.items():
                if len(part)<2:continue
                # Feed only through partition end. Runner consumes a requested
                # start in frame.attrs; baseline runner uses that same date.
                prefix=full[full.date<=part.date.max()].copy()
                prefix.attrs['evaluation_start']=part.date.min()
                sub=runner(prefix,fee_rate)
                stability.append({'name':name,'symbol':symbol,'partition':label,
                    'start':str(part.date.min().date()),'end':str(part.date.max().date()),
                    **sub.metrics,**additional_metrics(sub.daily,initial_capital)})
        return result
    def price_runner(strategy):
        def runner(data,cost):
            begin=data.attrs.get('evaluation_start',start)
            subset=data[data.date>=begin].reset_index(drop=True)
            return run_backtest(subset,strategy,initial_capital=initial_capital,fee_rate=cost,dca_months=dca_months)
        return runner
    def rule_runner(strategy):
        def runner(data,cost):
            return run_strategy_backtest(data,strategy,config,initial_capital=initial_capital,
                fee_rate=cost,start=data.attrs.get('evaluation_start',start))
        return runner
    def passive_runner(weight):
        def runner(data,cost):
            subset=data[data.date>=data.attrs.get('evaluation_start',start)].reset_index(drop=True)
            return passive_sleeve(subset,weight,initial_capital=initial_capital,fee_rate=cost)
        return runner
    def weight_runner(weight):
        def runner(data,cost):
            subset=data[data.date>=data.attrs.get('evaluation_start',start)].reset_index(drop=True)
            return allocation_reference(subset,weight,initial_capital=initial_capital,fee_rate=cost,rebalance=True)
        return runner
    add('沪深300ETF 买入持有','510300','核心比较',main,price_runner('hold'))
    add('沪深300ETF 固定月度分批投入','510300','核心比较',main,price_runner('dca'))
    add(NAMES['B'],'510300','核心比较',main,rule_runner('B'))
    # Fixed exposure must use the configured B target, not a fitted weight.
    from src.strategies import load_config
    active=load_config() if config is None else config
    b_cfg=active.get('B',active.get('strategies',{}).get('B',{}))
    fixed=float(b_cfg.get('target_weight',.8))
    add(f'简单初始{fixed:.0%}风险仓持有','510300','核心比较',main,passive_runner(fixed),metadata={'fixed_weight':fixed})
    add(f'每日恒定{fixed:.0%}风险仓','510300','核心比较',main,weight_runner(fixed),metadata={'fixed_weight':fixed})
    for strategy in ('A','C'):
        required={'pe_percentile','pb_percentile','valuation_available_at'}
        if strategy=='C':required|={'breadth_ratio','breadth_available_at'}
        # Full-history comparisons need each row's point-in-time evidence. No
        # partial prefix is disguised as a fully verified 2015 history.
        usable=required<=set(available_main.columns)
        if usable:usable=available_main[list(required)].notna().all().all()
        if usable:
            # Same close-time publication policy as the rule engine, not date-only
            # joins that silently leak a later publication into an earlier close.
            for prefix in ('valuation','breadth') if strategy=='C' else ('valuation',):
                for row in available_main[['date',prefix+'_available_at']].to_dict('records'):
                    try:
                        published=pd.Timestamp(row[prefix+'_available_at'])
                        if published.tzinfo is None:published=published.tz_localize('Asia/Shanghai')
                        deadline=pd.Timestamp(row['date']).normalize().tz_localize('Asia/Shanghai')+pd.Timedelta(hours=15,minutes=30)
                        if published>deadline:usable=False;break
                    except (ValueError,TypeError):usable=False;break
                if not usable:break
            for field in ('pe_percentile','pb_percentile','breadth_ratio') if strategy=='C' else ('pe_percentile','pb_percentile'):
                numeric=pd.to_numeric(available_main[field],errors='coerce')
                if numeric.isna().any() or not numeric.between(0,1).all():usable=False
        if usable:
            add(NAMES[strategy],'510300','核心比较',main,rule_runner(strategy))
        else:
            rows.append(dict(name=NAMES[strategy],symbol='510300',group='核心比较',status='历史数据不足',
                reason='缺少逐日、可验证发布时间的历史PE/PB百分位'+('与市场宽度' if strategy=='C' else '')+'；未用当前值或趋势代理回填',start=None,end=None,sessions=0))
    if index_prices is not None and not index_prices.empty:
        data=_closed_prices(index_prices,end)
        if len(data[data.date>=start])>=2:
            add('沪深300指数价格 买入持有（假设性）','000300','指数参考',data,price_runner('hold'))
    for symbol in ('159665','159992'):
        data=_closed_prices(datasets.get(symbol,pd.DataFrame()),end)
        if data.empty or len(data[data.date>=start])<2:
            rows.append(dict(name=NAMES['D']+' '+symbol,symbol=symbol,group='卫星独立比较',status='历史数据不足',reason='缺少该ETF价格历史',sessions=0))
            continue
        d_cfg=active.get('D',active.get('strategies',{}).get('D',{}))
        target=float(d_cfg.get('target_weight',.1))
        add(NAMES['D']+' '+symbol,symbol,'卫星独立比较',data,rule_runner('D'))
        add(f'{symbol} 初始{target:.0%}卫星仓持有',symbol,'卫星独立比较',data,passive_runner(target),metadata={'fixed_weight':target})
        add(f'{symbol} 每日恒定{target:.0%}卫星仓',symbol,'卫星独立比较',data,weight_runner(target),metadata={'fixed_weight':target})
        coverage[symbol]={'first_observation':str(data.date.min().date()),'rows':len(data),
            'note':'上市后可得历史；MA200预热不足时不交易；总资金的卫星上限，不与100%宽基直接排名'}
    coverage['510300']={'requested_start':str(start.date()),'start':str(available_main.date.min().date()),'end':str(available_main.date.max().date()),
        'rows':len(available_main),'warmup_rows':int((main.date<start).sum()),
        'sha256':hashlib.sha256(main.to_csv(index=False).encode()).hexdigest()}
    table=pd.DataFrame(rows)
    conclusion=conclusion_text(table,pd.DataFrame(stability),active.get('evaluation',{}))
    return dict(comparison=table,curves=curves,decisions=pd.DataFrame(decision_rows),
        stability=pd.DataFrame(stability),coverage=coverage,conclusion=conclusion,config=active,
        assumptions={'initial_capital':initial_capital,'fee_rate':fee_rate,'dca_months':dca_months,
                     'cash_yield':0,'execution':'T日收盘信号，T+1开盘执行','dividends':'未复权价格，不含分红'},
        limitations=[
            '2015至2017日历不在本地已验证日历覆盖内；数据首尾不等于逐交易日完整性验证。',
            '所有收益均为价格研究，未还原分红；沪深300指数价格不是可以直接成交的证券。',
            f'月度分批投入使用相同初始资金预留现金、分{dca_months}个月投入，不是新增工资现金流IRR。',
            '零成交量被视为整日暂停/无开盘成交的可成交性标记；不开仓、不卖出，不用T+1正成交量大小择时。该假设需真实停牌/开盘成交记录进一步验证；未计滑点、市场冲击、最低佣金、整数份额、税制或实盘成交限制。',
            'D按配置目标卫星仓与同权重静态仓比较，较低整体回撤不能归因于择时能力。',
            '年度和70/30分段从现金重新开始，不代表真实账户跨期持仓；首尾年度可能不完整。',
            '历史表现不保证未来收益或最大回撤，历史低于20%也不构成未来20%内的承诺。'])


def conclusion_text(table, stability, evaluation=None):
    evaluation=evaluation or {}
    dd_margin=float(evaluation.get("drawdown_improvement",.05))
    consistency_min=float(evaluation.get("annual_consistency",.6))
    return_slack=float(evaluation.get("annual_return_slack",.02))
    underwater_ratio=float(evaluation.get("max_underwater_ratio",1.))
    dispersion_ratio=float(evaluation.get("max_annual_dispersion_ratio",1.))
    valid=table[table.status=='可计算']
    b=valid[valid.name==NAMES['B']]
    simple=valid[valid.name.str.startswith('简单初始')]
    if b.empty or simple.empty:
        return '缺少可比证据，保留简单配置与定投作为基准，不认定复杂策略有效。'
    b=b.iloc[0];s=simple.iloc[0]
    # A predefined, disclosed diagnostic threshold, not optimized selection.
    dd_improvement=float(b.max_drawdown-s.max_drawdown)
    if not stability.empty and {'name','partition','max_drawdown'} <= set(stability.columns):
        stable_b=stability[(stability.name==b['name']) & stability.partition.str.fullmatch(r'\d{4}')]
        stable_s=stability[(stability.name==s['name']) & stability.partition.str.fullmatch(r'\d{4}')]
        matched=stable_b.merge(stable_s,on='partition',suffixes=('_b','_s'))
    else:
        matched=pd.DataFrame()
    consistency=float((matched.max_drawdown_b>matched.max_drawdown_s).mean()) if len(matched) else 0.
    underwater_b=float(b.get('max_underwater_sessions',float('inf')))
    underwater_s=float(s.get('max_underwater_sessions',0))
    dispersion_b=float(b.get('annual_return_dispersion',float('inf')))
    dispersion_s=float(s.get('annual_return_dispersion',0))
    stable=underwater_b<=underwater_s*underwater_ratio and dispersion_b<=dispersion_s*dispersion_ratio
    summary=f'同资产比较，B相对简单初始仓位持有最大回撤改善{dd_improvement*100:.2f}个百分点；可比年度中回撤较小比例{consistency:.1%}。'
    summary+=f'B/简单基准最长水下期为{underwater_b:.0f}/{underwater_s:.0f}个交易日，年度收益离散度为{dispersion_b:.2%}/{dispersion_s:.2%}，年化为{b.annual_return:.2%}/{s.annual_return:.2%}。'
    if dd_improvement>=dd_margin and consistency>=consistency_min and stable and b.annual_return>=s.annual_return-return_slack:
        summary+='B在本样本对控制回撤更符合目标，可作为待样本外复核的候选；这不证明未来有效。'
    else:
        summary+=f'未同时达到配置中的{dd_margin*100:g}个百分点回撤改善、{consistency_min:.0%}年度一致性、水下持续期不超过基准{underwater_ratio:g}倍、年度收益离散度不超过基准{dispersion_ratio:g}倍及年化落后不超过{return_slack*100:g}个百分点标准，建议保留简单策略。'
    if (table.status!='可计算').any():summary+='A/C历史覆盖不足，不能判定其优于B或简单配置；D应单独按同卫星额度评价。'
    return summary


def _format(value,percent=False):
    if pd.isna(value):return '—'
    return f'{float(value):.2%}' if percent else f'{float(value):.2f}'


def render_markdown(result,output_dir):
    t=result['comparison'];a=result['assumptions'];c=result['coverage']['510300']
    lines=['# 策略风险收益比较报告','',
        f"请求起始{c['requested_start']}至最新可得已完成日线；510300实际样本 {c['start']}—{c['end']}，{c['rows']}日，预热{c['warmup_rows']}行。",'',
        '目标是比较规则的风险收益，不预测涨跌。没有调用LLM；所有决策附原因，T日信号下一交易日开盘执行。','',
        '## 数据结论','',result['conclusion'],'',
        '评价顺序：最大回撤 → 年度稳定性/水下持续期 → 年化收益。B候选筛选阈值预先声明，并未优化到本样本；完整历史五维数据缺失时不做胜出宣称。','',
        '## 策略比较','',
        '| 策略 | 分组 | 状态 | 年化 | 最大回撤 | 波动率 | 夏普 | 卡玛 | 最差年度 | 最长水下交易日 | 连跌交易日 | 交易次数 | 费用元 | 费用影响百分点 |',
        '|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for row in t.to_dict('records'):
        numeric=[]
        for key,pct in [('annual_return',True),('max_drawdown',True),('volatility',True),('sharpe',False),('calmar',False),('worst_year',True),('max_underwater_sessions',False),('max_losing_streak_sessions',False),('trades',False),('fees',False),('fee_impact_return_pp',False)]:
            numeric.append(_format(row.get(key,float('nan')),pct))
        lines.append('| '+' | '.join([row['name'],row['group'],row['status'],*numeric])+' |')
    lines+=['','A/C不可用原因：缺少完整逐日历史PE/PB及其可用时间，C另缺历史宽度；不拿当前值回填。D按每只ETF可得历史起算，不伪造2015年前上市历史。','',
        '“最长水下交易日”从净值低于历史高水位开始计数，到恢复前高结束，包括样本末仍未恢复的区间；“连跌交易日”只计连续负日收益。不是按月亏损期。','',
        '费用影响 = 同一规则零费用终值减实际费用终值，再除相同初始资金；重算全部交易，包含费用对后续持仓的影响。','',
        '## 图表和审计文件','',
        f'- [净值/回撤交互图]({output_dir}/nav_drawdown.html)（独立HTML，浏览器打开，无需联网）。',
        f'- [完整对比表]({output_dir}/comparison.csv)',f'- [年度及前70%/后30%诊断]({output_dir}/stability.csv)',
        f'- [逐日策略决策和原因]({output_dir}/decisions.csv)',f'- [来源与配置快照]({output_dir}/metadata.json)','',
        '## 比较口径','',
        f"初始资金{a['initial_capital']:.0f}元，单边手续费{a['fee_rate']:.2%}；闲置现金零收益，月度分批投入使用预留资金。所有曲线从相同资金起算，不注入不等额资金。",'',
        '简单初始仓位持有只在首日买入一次，此后不再平衡、仓位可漂移；每日恒定仓位则每个交易日按前一日目标再平衡，交易次数和费用完整计入。D与同资产、同初始卫星额度的持有和每日恒定基准分组比较；不把低风险仓位造成的回撤下降称为择时超额收益。A/C当前不可计算，不画虚构净值。','',
        '## 限制','',*['- '+x for x in result['limitations']],'',
        '## 重现','', '```bash','python -m jobs.strategy_report','pytest -q','```','']
    return '\n'.join(lines)


def write_artifacts(result, output_dir, report_path):
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    output_dir=Path(output_dir);output_dir.mkdir(parents=True,exist_ok=True)
    for key in ('comparison','decisions','stability'):
        result[key].to_csv(output_dir/f'{key}.csv',index=False,encoding='utf-8-sig')
    fig=make_subplots(rows=2,cols=1,shared_xaxes=True,subplot_titles=('净值（相同初始资金）','回撤（相对起始资金及历史峰值）'),vertical_spacing=.12)
    for name,data in result['curves'].items():
        fig.add_trace(go.Scatter(x=data.date,y=data.nav,name=name,legendgroup=name),row=1,col=1)
        fig.add_trace(go.Scatter(x=data.date,y=data.drawdown,name=name,legendgroup=name,showlegend=False),row=2,col=1)
    fig.update_layout(height=900,title='策略风险收益研究：未复权价格，不含分红；D为独立低额度卫星仓',legend=dict(orientation='h',y=-.15))
    fig.update_yaxes(tickformat='.0%',row=2,col=1)
    chart_path=output_dir/'nav_drawdown.html'
    fig.write_html(chart_path,include_plotlyjs=True,full_html=True)
    # Plotly embeds shader source with trailing spaces; normalize generated text
    # without changing line breaks or the standalone script.
    chart_path.write_text('\n'.join(line.rstrip() for line in chart_path.read_text().splitlines())+'\n')
    metadata={key:result[key] for key in ('coverage','config','assumptions','limitations','conclusion')}
    (output_dir/'metadata.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2,default=_scalar,allow_nan=False))
    report_path=Path(report_path)
    import os
    relative=Path(os.path.relpath(output_dir,report_path.resolve().parent)).as_posix()
    report_path.write_text(render_markdown(result,relative))


def generate_report(db_path=None, output_dir='reports/strategies',report_path='STRATEGY_REPORT.md',*,start='2015-01-01',end=None,config=None,fee_rate=.0003,initial_capital=CAPITAL,dca_months=12):
    data,index=load_public_data(db_path or load_settings().db_path)
    result=build_comparison(data,index_prices=index,start=start,end=end,config=config,fee_rate=fee_rate,initial_capital=initial_capital,dca_months=dca_months)
    write_artifacts(result,output_dir,report_path)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',type=Path,default=load_settings().db_path)
    parser.add_argument('--output',type=Path,default=Path('reports/strategies'))
    parser.add_argument('--report',type=Path,default=Path('STRATEGY_REPORT.md'))
    parser.add_argument('--start',default='2015-01-01');parser.add_argument('--end')
    parser.add_argument('--config',type=Path,help='JSON strategy configuration; defaults to config/strategies.json')
    parser.add_argument('--fee-rate',type=float,default=.0003)
    parser.add_argument('--capital',type=float,default=CAPITAL)
    parser.add_argument('--dca-months',type=int,default=12)
    args=parser.parse_args()
    from src.strategies import load_config
    config=load_config(args.config)
    result=generate_report(args.db,args.output,args.report,start=args.start,end=args.end,config=config,fee_rate=args.fee_rate,initial_capital=args.capital,dca_months=args.dca_months)
    print(result['conclusion'])
    print(f"Report: {args.report}; comparison rows: {len(result['comparison'])}")

if __name__=='__main__':main()
