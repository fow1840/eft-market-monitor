import copy
import numpy as np
import pandas as pd
import pytest
from src.strategies import load_config, validate_config, evaluate, make_features, run_strategy_backtest, STATES, ACTIONS


def row(**kwargs):
    return dict(date=pd.Timestamp('2024-01-31'),close=120.,ma_short=115.,ma_medium=110.,ma_long=100.,ma_long_prev=99.,volume_ratio=1.2,
                pe_percentile=.2,pb_percentile=.2,valuation_available_at='2024-01-31 15:00',breadth_ratio=.7,breadth_available_at='2024-01-31 15:00',
                shares_change5=.03,shares_available_at='2024-01-31 08:00',cross_above_short=True,pullback_seen=True,**kwargs)


def changed(**kwargs):
    result=row();result.update(kwargs);return result

# Explicitly hand-built scenarios: state/action/target arithmetic is independently asserted.
@pytest.mark.parametrize('strategy,change,weight,state,action',[
    ('A',{},.3,'改善','正常买入'),
    ('A',{'pe_percentile':.5,'pb_percentile':.5},.3,'中性','小额增加'),
    ('A',{'pe_percentile':.9,'pb_percentile':.9},.3,'中性','持有不动'),
    ('A',{'close':90.},.6,'偏弱','持有不动'),
    ('A',{},.66,'偏弱','降低风险仓'),
    ('A',{},.62,'改善','暂停新增'),
    ('B',{},.3,'强','正常买入'),
    ('B',{'close':90.},.6,'弱','降低风险仓'),
    ('B',{'close':90.},.1,'弱','暂停新增'),
    ('B',{'close':112.},.3,'改善','小额增加'),
    ('B',{'close':105.},.3,'偏弱','暂停新增'),
    ('B',{},.66,'偏弱','降低风险仓'),
    ('C',{},.3,'强','正常买入'),
    ('C',{'volume_ratio':.8},.3,'改善','小额增加'),
    ('C',{'breadth_ratio':.2},.3,'偏弱','暂停新增'),
    ('C',{'pe_percentile':.9,'pb_percentile':.9},.3,'中性','持有不动'),
    ('C',{'close':90.},.6,'弱','降低风险仓'),
    ('C',{'close':112.},.3,'改善','小额增加'),
    ('C',{},.62,'强','暂停新增'),
    ('D',{},.02,'改善','小额增加'),
    ('D',{'cross_above_short':False},.02,'中性','持有不动'),
    ('D',{'pullback_seen':False},.02,'中性','持有不动'),
    ('D',{'volume_ratio':.8},.02,'中性','持有不动'),
    ('D',{'close':105.},.1,'偏弱','降低风险仓'),
    ('D',{'close':90.},.1,'弱','降低风险仓'),
    ('D',{},.102,'偏弱','降低风险仓'),
])
def test_manual_scenarios(strategy,change,weight,state,action):
    decision=evaluate(strategy,changed(**change),weight)
    assert decision['state']==state
    assert decision['action']==action
    assert decision['reasons']
    assert decision['available'] is True
    assert 0<=decision['target_weight']<1


def test_hand_calculated_buy_and_rebalance():
    assert evaluate('A',row(),.3)['target_weight']==pytest.approx(.35)
    assert evaluate('A',changed(pe_percentile=.5,pb_percentile=.5),.3)['target_weight']==pytest.approx(.32)
    assert evaluate('B',changed(close=90),.6)['target_weight']==.2
    assert evaluate('D',row(),.102)['target_weight']==.1
    assert evaluate('A',row(),.65)['action']=='暂停新增' # exactly five pp: no rebalance


@pytest.mark.parametrize('strategy', ['A','B','C','D'])
def test_missing_and_invalid_market_data(strategy):
    decision=evaluate(strategy,changed(ma_long=np.nan),.3)
    # D position cap still operates before missing data checks.
    if strategy=='D':assert decision['action']=='降低风险仓'
    else:
        assert not decision['available']
        assert decision['target_weight']==.3


@pytest.mark.parametrize('strategy', ['A','C'])
def test_future_fundamentals_cannot_trigger_buy(strategy):
    decision=evaluate(strategy,changed(valuation_available_at='2024-02-01'),.3)
    assert not decision['available'] and decision['action']=='暂停新增'
    assert decision['target_weight']==.3


def test_c_missing_data_does_not_prevent_risk_reduction():
    d=evaluate('C',changed(close=90,valuation_available_at=None,breadth_available_at=None),.6)
    assert d['target_weight']==.2 and d['action']=='降低风险仓'


def test_c_future_breadth_rejected_and_shares_only_auxiliary():
    d=evaluate('C',changed(breadth_available_at='2024-02-01'),.3)
    assert not d['available']
    d=evaluate('C',changed(shares_available_at=None),.3)
    assert d['available'] and d['state']=='强'


def data(n=260):
    close=100+np.arange(n)*.1
    return pd.DataFrame(dict(date=pd.bdate_range('2023-01-02',periods=n),open=close,close=close,volume=1000.))


def test_features_hand_calculated_and_prefix_invariance():
    d=data();f=make_features(d)
    assert f.ma_short.iloc[19]==pytest.approx(sum(d.close.iloc[:20])/20)
    assert f.ma_medium.iloc[59]==pytest.approx(sum(d.close.iloc[:60])/60)
    assert f.ma_long.iloc[199]==pytest.approx(sum(d.close.iloc[:200])/200)
    pd.testing.assert_frame_equal(make_features(d.iloc[:230]),f.iloc[:230])
    altered=d.copy();altered.loc[230:,'close']=10000
    pd.testing.assert_frame_equal(make_features(altered).iloc[:230],f.iloc[:230])


def test_next_open_execution_and_stateful_weights():
    d=data();result=run_strategy_backtest(d,'B',initial_capital=100000,fee_rate=0)
    decisions=result.decisions
    first=decisions[decisions.action=='正常买入'].index[0]
    assert result.daily.units.iloc[first]==0
    assert result.daily.units.iloc[first+1]==pytest.approx(5000/d.open.iloc[first+1])
    # At first executed close actual weight is computed, not an invented cumulative target.
    expected=result.daily.units.iloc[first+1]*d.close.iloc[first+1]/result.daily.equity.iloc[first+1]
    assert decisions.current_weight.iloc[first+1]==pytest.approx(expected)
    assert decisions.target_weight.iloc[first+1]==pytest.approx(expected+.05)
    truncated=run_strategy_backtest(d.iloc[:240],'B',fee_rate=0)
    pd.testing.assert_frame_equal(truncated.daily,result.daily.iloc[:240])


def test_prefix_decisions_all_strategies():
    d=data()
    for strategy in ('A','B','C','D'):
        full=run_strategy_backtest(d,strategy)
        prefix=run_strategy_backtest(d.iloc[:240],strategy)
        pd.testing.assert_frame_equal(prefix.decisions,full.decisions.iloc[:240])


def test_pre_start_warmup_and_fees():
    d=data()
    start=d.date.iloc[220]
    full=run_strategy_backtest(d,'B',start=start,fee_rate=.001)
    assert full.decisions.available.all()
    assert full.daily.units.iloc[0]==0
    assert full.daily.fee.sum()>0
    nofee=run_strategy_backtest(d,'B',start=start,fee_rate=0)
    assert full.daily.equity.iloc[-1]<nofee.daily.equity.iloc[-1]


@pytest.mark.parametrize('section,key,value',[
    ('windows','long',10),('windows','short',True),('thresholds','buy_step',float('nan')),
    ('thresholds','allocation_band',-1),('thresholds','low_valuation',.9),
    ('B','risk_weight',0),('B','max_weight',1),('D','target_weight',.8),
])
def test_config_validation(section,key,value):
    config=load_config();config[section][key]=value
    with pytest.raises(ValueError):evaluate('B',row(),.3,config)


def test_all_rules_use_config_and_invalid_inputs():
    config=load_config();config['thresholds']['buy_step']=.04
    assert evaluate('B',row(),.3,config)['target_weight']==pytest.approx(.34)
    for weight in (-1,float('nan'),True):
        with pytest.raises(ValueError):evaluate('A',row(),weight)
    with pytest.raises(ValueError):evaluate('E',row(),.3)
    with pytest.raises(ValueError):run_strategy_backtest(data(),'B',fee_rate=-.1)

@pytest.mark.parametrize('strategy',['A','B','C','D'])
def test_missing_volume_does_not_block_price_risk_reduction(strategy):
    r=changed(close=90,volume_ratio=None)
    decision=evaluate(strategy,r,.6 if strategy!='D' else .1)
    if strategy in ('B','C','D'):
        assert decision['action']=='降低风险仓'
        assert decision['target_weight']>0
    else:assert decision['action']=='持有不动'


def test_b_pure_trend_and_c_confirmation_volume_missing():
    assert evaluate('B',changed(volume_ratio=None),.3)['action']=='正常买入'
    assert evaluate('C',changed(volume_ratio=None),.3)['action']=='小额增加'
    assert evaluate('D',changed(volume_ratio=None),.02)['action']=='持有不动'


def test_suspension_cannot_execute_at_untradable_open():
    d=data();base=run_strategy_backtest(d,'B',fee_rate=0)
    first=base.daily[base.daily.trades>0].index[0]
    d.loc[first,'volume']=0
    result=run_strategy_backtest(d,'B',fee_rate=0)
    assert result.daily.trades.iloc[first]==0
    assert result.daily.units.iloc[first]==0


@pytest.mark.parametrize('section,key,value',[('evaluation','annual_consistency',2),('execution','minimum_volume',-1)])
def test_report_and_execution_config_validation(section,key,value):
    config=load_config();config[section][key]=value
    with pytest.raises(ValueError):evaluate('B',row(),.3,config)


def test_aware_date_cannot_extend_publication_cutoff():
    d=changed(date=pd.Timestamp('2024-01-31T00:00:00Z'),valuation_available_at='2024-01-31T16:00:00+08:00')
    assert evaluate('A',d,.3)['available'] is False
    assert evaluate('C',d,.3)['available'] is False


def test_d_midterm_risk_does_not_wait_for_longterm_warmup():
    d=evaluate('D',changed(close=105,ma_long=float('nan'),ma_long_prev=float('nan')),.1)
    assert d['action']=='降低风险仓' and d['target_weight']==.02


def test_stability_ratio_parameters_validated():
    c=load_config();c['evaluation']['max_underwater_ratio']=0
    with pytest.raises(ValueError):evaluate('B',row(),.3,c)
