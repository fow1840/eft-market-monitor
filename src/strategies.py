"""Configurable, deterministic close-time policies; no prediction or LLM calls.

Weights are fractions of a whole portfolio. A D-sleeve of 10% includes 90%
non-risk cash in the backtest; compare it with an equally sized passive sleeve.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import time
from pathlib import Path
import copy
import json
import math
import numpy as np
import pandas as pd
from src.backtest import validate_prices, performance_metrics

STATES = ('强','改善','中性','偏弱','弱')
ACTIONS = ('正常买入','小额增加','持有不动','暂停新增','降低风险仓')
DEFAULT_PATH = Path(__file__).resolve().parents[1]/'config'/'strategies.json'


def validate_config(config):
    for section in ('windows','thresholds','A','B','C','D','evaluation','execution'):
        if section not in config or not isinstance(config[section],dict):raise ValueError('missing config section '+section)
    for field in ('short','medium','long','volume','pullback'):
        value=config['windows'].get(field)
        if isinstance(value,bool) or not isinstance(value,int) or value<2:raise ValueError('windows must be integers >=2')
    w=config['windows']
    if not w['short']<w['medium']<w['long']:raise ValueError('short < medium < long required')
    t=config['thresholds']
    for field in ('low_valuation','high_valuation','broad_strong','broad_weak','volume_confirm','shares_inflow','allocation_band','buy_step','small_buy_step','trade_tolerance'):
        if field not in t or isinstance(t[field],bool) or not isinstance(t[field],(int,float)) or not math.isfinite(t[field]):raise ValueError('invalid threshold '+field)
    if not 0<=t['low_valuation']<t['high_valuation']<=1:raise ValueError('invalid valuation bands')
    if not 0<=t['broad_weak']<t['broad_strong']<=1:raise ValueError('invalid breadth bands')
    if t['volume_confirm']<=0 or not 0<=t['shares_inflow']<=1:raise ValueError('invalid confirmation thresholds')
    if not 0<=t['allocation_band']<1 or not 0<t['trade_tolerance']<1:raise ValueError('invalid allocation band/tolerance')
    if not 0<t['small_buy_step']<=t['buy_step']<=1:raise ValueError('invalid buy steps')
    for strategy in ('A','B','C','D'):
        values=config[strategy]
        for key in ('min_weight','target_weight','max_weight','risk_weight'):
            value=values.get(key)
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):raise ValueError('invalid weight')
        if not 0<values['min_weight']<=values['risk_weight']<=values['target_weight']<=values['max_weight']<1:raise ValueError('weights must be nonbinary ordered fractions')
    for field in ('drawdown_improvement','annual_consistency','annual_return_slack'):
        value=config['evaluation'].get(field)
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=1:
            raise ValueError('invalid evaluation threshold')
    for field in ('max_underwater_ratio','max_annual_dispersion_ratio'):
        value=config['evaluation'].get(field)
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:
            raise ValueError('invalid stability ratio')
    value=config['execution'].get('minimum_volume')
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:
        raise ValueError('invalid minimum volume')
    return config


def load_config(path=None):
    return validate_config(json.loads(Path(path or DEFAULT_PATH).read_text()))


def _config(config):
    return load_config() if config is None else validate_config(copy.deepcopy(config))


def make_features(data, config=None):
    config=_config(config)
    prices=validate_prices(data)
    if 'volume' not in data:raise ValueError('volume required')
    frame=data.copy().reset_index(drop=True)
    frame[['date','open','close']]=prices[['date','open','close']]
    frame['volume']=pd.to_numeric(frame.volume,errors='raise')
    if not np.isfinite(frame.volume).all() or (frame.volume<0).any():raise ValueError('invalid volume')
    for name in ('short','medium','long'):
        frame['ma_'+name]=frame.close.rolling(config['windows'][name],min_periods=config['windows'][name]).mean()
    frame['ma_long_prev']=frame.ma_long.shift(1)
    mean=frame.volume.rolling(config['windows']['volume']).mean()
    frame['volume_ratio']=frame.volume/mean.replace(0,np.nan)
    below=frame.close<frame.ma_short
    frame['pullback_seen']=below.shift(1).rolling(config['windows']['pullback'],min_periods=1).max().fillna(0).astype(bool)
    frame['cross_above_short']=(frame.close>frame.ma_short)&(frame.close.shift(1)<=frame.ma_short.shift(1))
    return frame


def _finite(value):
    try:return not isinstance(value,(bool,np.bool_)) and math.isfinite(float(value))
    except (TypeError,ValueError):return False


def _published(row, prefix):
    """A supplied observation requires an explicit publication time, never an asof guess."""
    value=row.get(prefix+'_available_at')
    if value is None or pd.isna(value):return False
    try:
        published=pd.Timestamp(value)
        signal=pd.Timestamp(row['date'])
        signal=signal.tz_localize('Asia/Shanghai') if signal.tzinfo is None else signal.tz_convert('Asia/Shanghai')
        signal=signal.normalize()+pd.Timedelta(hours=15,minutes=30)
        if published.tzinfo is None:published=published.tz_localize('Asia/Shanghai')
        if signal.tzinfo is None:signal=signal.tz_localize('Asia/Shanghai')
        return published<=signal
    except (ValueError,TypeError,KeyError):return False


def evaluate(strategy, row, current_weight, config=None):
    config=_config(config)
    if strategy not in ('A','B','C','D'):raise ValueError('unknown strategy')
    if not _finite(current_weight) or not 0<=current_weight<=1:raise ValueError('weight must be in [0,1]')
    p=config[strategy];t=config['thresholds'];current=float(current_weight)
    reasons=[]
    def result(state,action,target,available=True):
        return dict(state=state,action=action,target_weight=float(min(1,max(0,target))),reasons=reasons.copy(),available=available)
    # Allocation constraints are checked before every market indicator and publication check.
    if current>p['max_weight']+t['trade_tolerance'] or current-p['target_weight']>t['allocation_band']+1e-12 or (strategy=='D' and current>p['target_weight']+t['trade_tolerance']):
        reasons.append('仓位超过上限或目标偏离带，仓位约束优先于市场信号')
        return result('偏弱','降低风险仓',p['target_weight'])
    # Any overweight blocks purchases even inside the rebalance band.
    overweight=current>p['target_weight']+t['trade_tolerance']
    # Available price risk limits cannot be overridden by missing auxiliary history.
    long_break=_finite(row.get('close')) and _finite(row.get('ma_long')) and float(row['close'])<float(row['ma_long'])
    mid_break=_finite(row.get('close')) and _finite(row.get('ma_medium')) and float(row['close'])<float(row['ma_medium'])
    if (strategy in ('B','C') and long_break) or (strategy=='D' and (long_break or mid_break)):
        desired=min(current,p['risk_weight'])
        reasons.append('已可验证的长期/中期风险限制优先于缺失的买入确认指标')
        complete=True
        if strategy=='C':
            complete=_published(row,'valuation') and _published(row,'breadth') and all(_finite(row.get(k)) and 0<=float(row[k])<=1 for k in ('pe_percentile','pb_percentile','breadth_ratio'))
        return result('弱' if long_break else '偏弱','降低风险仓' if desired<current else '暂停新增',desired,complete)
    features=('close','ma_short','ma_medium','ma_long','ma_long_prev')
    if not all(_finite(row.get(key)) for key in features):
        reasons.append('均线/量能预热不足或数据缺失，暂停新增，保留现有仓位')
        return result('中性','暂停新增',current,False)
    close=float(row['close']);short=float(row['ma_short']);medium=float(row['ma_medium']);long=float(row['ma_long'])
    long_up=close>long and long>=float(row['ma_long_prev'])
    medium_up=close>short>medium
    long_broken=close<long
    volume_ok=_finite(row.get('volume_ratio')) and float(row['volume_ratio'])>=t['volume_confirm']
    value=None
    if strategy in ('A','C'):
        if not _published(row,'valuation') or not all(_finite(row.get(k)) and 0<=float(row[k])<=1 for k in ('pe_percentile','pb_percentile')):
            reasons.append('缺少决策时点已发布的PE/PB历史分位，不能以当前估值回填历史')
            return result('中性','暂停新增',current,False)
        value=(float(row['pe_percentile'])+float(row['pb_percentile']))/2
    if strategy=='C':
        if not _published(row,'breadth') or not _finite(row.get('breadth_ratio')) or not 0<=float(row['breadth_ratio'])<=1:
            reasons.append('缺少决策时点已发布的市场宽度，暂停方向判断')
            return result('中性','暂停新增',current,False)
    if strategy=='A':
        # Core stays invested; valuation only accelerates already planned, trend-confirmed buying.
        if long_up and medium_up and value<=t['low_valuation']:
            state='改善';desired=min(p['target_weight'],current+t['buy_step'])
            action='正常买入';reasons.append('估值偏低且长期/中期趋势确认，在目标内增加计划买入')
        elif long_up and medium_up and value<t['high_valuation']:
            state='中性';desired=min(p['target_weight'],current+t['small_buy_step']);action='小额增加';reasons.append('核心宽基按目标计划买入，不因短期涨跌清仓')
        else:
            state='偏弱' if long_broken else '中性';desired=current;action='持有不动';reasons.append('保留长期核心配置；低估值不能独立触发逆势买入')
    elif strategy=='B':
        if long_broken:
            state='弱';desired=min(current,p['risk_weight']);action='降低风险仓' if desired<current else '暂停新增';reasons.append('收盘低于长期均线，风险仓降至非零风险下限')
        elif long_up and medium_up:
            state='强';desired=min(p['target_weight'],current+t['buy_step']);action='正常买入';reasons.append('MA长期方向向上，且收盘/短期/中期均线依次向上')
        elif long_up and close>medium:
            state='改善';desired=min(p['target_weight'],current+t['small_buy_step']);action='小额增加';reasons.append('长期向上且站上中期均线，中期趋势改善')
        else:
            state='偏弱';desired=current;action='暂停新增';reasons.append('趋势尚未完成确认，暂停新增而非全仓/空仓切换')
    elif strategy=='C':
        breadth=float(row['breadth_ratio'])
        reasons.append(f'估值同口径历史分位均值{value:.1%}，市场上涨比例{breadth:.1%}')
        if long_broken:
            state='弱';desired=min(current,p['risk_weight']);action='降低风险仓' if desired<current else '暂停新增';reasons.append('MA长期趋势破坏；估值低不能覆盖风险限制')
        elif breadth<t['broad_weak']:
            state='偏弱';desired=current;action='暂停新增';reasons.append('市场宽度不足，价格趋势质量未获确认')
        elif long_up and medium_up and breadth>=t['broad_strong'] and value<t['high_valuation']:
            state='强' if volume_ok else '改善';desired=min(p['target_weight'],current+(t['buy_step'] if volume_ok else t['small_buy_step']));action='正常买入' if volume_ok else '小额增加';reasons.append('长期与中期向上，估值未偏高，宽度确认；量能仅决定确认强度')
        elif long_up and close>medium and value<t['high_valuation']:
            state='改善';desired=min(p['target_weight'],current+t['small_buy_step']);action='小额增加';reasons.append('长期向上，中期修复且估值未偏高，目标内小额增加')
        else:
            state='中性';desired=current;action='持有不动';reasons.append('条件未形成一致确认，保持现有仓位')
        if _published(row,'shares') and _finite(row.get('shares_change5')):
            reasons.append('ETF份额为辅助指标：'+('增加' if float(row['shares_change5'])>t['shares_inflow'] else '未显著增加'))
        else:reasons.append('ETF份额不可用，不代替趋势/估值/宽度判断')
    else:
        if long_broken or close<medium:
            state='弱' if long_broken else '偏弱';desired=min(current,p['risk_weight']);action='降低风险仓' if desired<current else '暂停新增';reasons.append('跌破长期或中期均线，降低卫星风险仓')
        elif long_up and bool(row.get('cross_above_short',False)) and bool(row.get('pullback_seen',False)) and volume_ok:
            state='改善';desired=min(p['target_weight'],current+t['small_buy_step']);action='小额增加';reasons.append('长期向上，回调后重新站上短期均线并有量能确认')
        else:
            state='中性';desired=current;action='持有不动';reasons.append('卫星入场条件未齐：需长期向上、回调重上短均线与量能同时确认')
    if overweight and action in ('正常买入','小额增加'):
        reasons.append('当前已超过目标，即使市场强也暂停新增')
        return result(state,'暂停新增',current)
    # In-band A core does not sell/rebalance on price movements.
    if desired>current and p['target_weight']-current<=t['trade_tolerance']:
        desired=current;action='持有不动';reasons.append('已达到计划目标，不重复买入')
    if abs(desired-current)<=t['trade_tolerance']:
        desired=current
        if action in ('正常买入','小额增加','降低风险仓'):action='持有不动'
    return result(state,action,desired)


@dataclass
class StrategyBacktestResult:
    daily: pd.DataFrame
    metrics: dict
    decisions: pd.DataFrame
    assumptions: str


def run_strategy_backtest(data,strategy,config=None,*,initial_capital=100000,fee_rate=.0003,start=None):
    config=_config(config)
    if not _finite(initial_capital) or initial_capital<=0 or not _finite(fee_rate) or not 0<=fee_rate<1:raise ValueError('invalid capital/fee')
    frame=make_features(data,config)
    if start is not None:frame=frame[frame.date>=pd.Timestamp(start)].reset_index(drop=True)
    if len(frame)<2:raise ValueError('at least two evaluation dates required')
    cash=float(initial_capital);units=0.;pending=None;pending_day=None;daily=[];decisions=[]
    for row in frame.to_dict('records'):
        equity_open=cash+units*row['open'];fee=0.;trades=0
        signal_day=pending_day
        execution_status='no_order' if pending is None else 'within_tolerance'
        if pending is not None and row['volume']<=config['execution']['minimum_volume']:
            execution_status='cancelled_untradable_open'
        if pending is not None and row['volume']>config['execution']['minimum_volume']:
            weight=units*row['open']/equity_open
            if abs(weight-pending)>config['thresholds']['trade_tolerance']:
                target=pending*equity_open;difference=target-units*row['open']
                if difference<0:
                    sold=min(units,-difference/row['open']);proceeds=sold*row['open'];fee=proceeds*fee_rate;units-=sold;cash+=proceeds-fee;trades=1
                elif difference>0:
                    budget=min(cash,difference*(1+fee_rate));notional=budget/(1+fee_rate);fee=budget-notional;cash-=budget;units+=notional/row['open'];trades=1
        if trades:execution_status='executed'
        equity=cash+units*row['close'];current=units*row['close']/equity
        decision=evaluate(strategy,row,current,config)
        if row['volume']<=config['execution']['minimum_volume'] and decision['action'] in ('正常买入','小额增加'):
            decision.update(action='暂停新增',target_weight=current,available=False)
            decision['reasons'].append('零成交或低于配置阈值，暂停新增且取消不可成交订单')
        # A hold/no-add action must not rebalance a drifting weight at tomorrow's open.
        pending=decision['target_weight'] if decision['action'] in ('正常买入','小额增加','降低风险仓') else None
        pending_day=row['date'] if pending is not None else None
        decisions.append({'date':row['date'],'current_weight':current,**decision})
        daily.append({'date':row['date'],'equity':equity,'cash':cash,'units':units,'fee':fee,'trades':trades,'weight':current,'execution_status':execution_status,'signal_date':signal_day})
    daily=pd.DataFrame(daily);metrics=performance_metrics(daily,initial_capital)
    returns=daily.equity.div(daily.equity.shift(1).fillna(initial_capital)).sub(1)
    losing=returns<0;groups=(~losing).cumsum()
    metrics['max_consecutive_loss_sessions']=int(losing.groupby(groups).sum().max())
    underwater=daily.equity<pd.concat([pd.Series([initial_capital]),daily.equity],ignore_index=True).cummax().iloc[1:].to_numpy()
    metrics['max_underwater_sessions']=int(underwater.groupby((~underwater).cumsum()).sum().max())
    return StrategyBacktestResult(daily,metrics,pd.DataFrame(decisions),'T close decision at T+1 open; equal initial capital; residual cash zero yield; no dividends/slippage; fractional shares; unavailable inputs never fabricated')
