from decimal import Decimal
import pytest
from src.rebalance import plan_rebalance,split_cents


def row(id,name,amount,bucket,status='free',**kwargs):
    return dict(id=id,name=name,amount=amount,bucket=bucket,holding_status=status,**kwargs)


def standard(status='free'):
    return [row('s','卫星示例',800,'卫星',status),row('c','核心示例',200,'核心宽基')]


def integer_sum(rows,key='amount'):
    return sum(round(r[key]*100) for r in rows)


def test_hand_calculated_quarter_plan_and_cash_conservation():
    r=plan_rebalance(standard(),{'卫星':.2,'核心宽基':.8})
    sell,buy=r['holdings']
    assert sell['final_adjustment_amount']==-600
    assert buy['final_adjustment_amount']==600
    assert sell['round_amount']==-150 and buy['round_amount']==150
    assert sell['executable_amount']==-150 and buy['executable_amount']==150
    assert sell['estimated_amount']==650 and buy['estimated_amount']==350
    assert integer_sum(r['simulation'])==100000==integer_sum(r['executable_simulation'])
    assert sell['action']=='减仓多少' and buy['action']=='买入多少'
    assert any('核心仓低配' in x for x in r['warnings'])


@pytest.mark.parametrize('status',['unknown','locked','需人工确认',None])
def test_unknown_or_locked_sells_cannot_fund_execution(status):
    r=plan_rebalance(standard(status),{'卫星':.2,'核心宽基':.8})
    assert [h['executable_amount'] for h in r['holdings']]==[0,0]
    assert [h['round_amount'] for h in r['holdings']]==[-150,150]
    assert integer_sum(r['executable_simulation'])==100000
    assert any('理论' in reason for h in r['holdings'] for reason in h['reasons'])


def test_only_confirmed_partial_sales_finance_buys():
    holdings=[row('a','未知',400,'卫星','unknown'),row('b','已确认',400,'卫星'),row('c','核心',200,'核心宽基')]
    r=plan_rebalance(holdings,{'卫星':.2,'核心宽基':.8})
    assert [x['round_amount'] for x in r['holdings']]==[-75,-75,150]
    assert [x['executable_amount'] for x in r['holdings']]==[0,-75,75]
    assert integer_sum(r['simulation'])==integer_sum(r['executable_simulation'])==100000


@pytest.mark.parametrize('amount,expected',[(550,False),(551,True),(450,False),(449,True)])
def test_exact_five_percentage_point_boundary(amount,expected):
    holdings=[row('a','甲',amount,'甲'),row('b','乙',1000-amount,'乙')]
    r=plan_rebalance(holdings,{'甲':.5,'乙':.5})
    assert r['buckets'][0]['triggered'] is expected
    if not expected:assert all(x['round_amount']==0 for x in r['holdings'])


def test_only_sell_bucket_leaves_explicit_cash_not_disappearing_assets():
    holdings=[row('a','甲',600,'甲'),row('b','乙',200,'乙'),row('c','丙',200,'丙')]
    r=plan_rebalance(holdings,{'甲':.5,'乙':.25,'丙':.25})
    assert r['cash_reserve']==25
    assert r['simulation'][-1]['name']=='待分配现金'
    assert integer_sum(r['simulation'])==100000


def test_only_buy_bucket_requires_funding_never_assumes_external_cash():
    holdings=[row('a','甲',400,'甲'),row('b','乙',300,'乙'),row('c','丙',300,'丙')]
    r=plan_rebalance(holdings,{'甲':.5,'乙':.25,'丙':.25})
    assert r['funding_shortfall']==25 and all(x['round_amount']==0 for x in r['holdings'])
    assert r['holdings'][0]['action']=='暂停加仓'
    assert integer_sum(r['simulation'])==100000


def test_missing_bucket_does_not_invent_fund_selection():
    r=plan_rebalance([row('a','卫星',1000,'卫星')],{'卫星':.5,'核心宽基':.5})
    virtual=next(x for x in r['holdings'] if x['virtual'])
    assert virtual['name']=='待指定基金' and virtual['action']=='暂停加仓'
    assert virtual['round_amount']==125 and virtual['executable_amount']==0
    assert r['executable_cash_reserve']==125
    assert integer_sum(r['simulation'])==integer_sum(r['executable_simulation'])==100000


def test_duplicates_legitimate_accounts_are_summed_not_deleted():
    holdings=[row('a','示例 基金',100,'甲',account='账户一'),row('b','示例基金',100,'甲',account='账户二')]
    r=plan_rebalance(holdings,{'甲':1})
    assert r['total_amount']==200 and len(r['holdings'])==2
    assert any('重复基金' in x for x in r['warnings'])


def test_theme_overweight_pauses_buys_but_no_unknown_caps_invented():
    holdings=[row('a','甲',300,'甲',themes=['科技']),row('b','乙',700,'乙')]
    r=plan_rebalance(holdings,{'甲':.5,'乙':.5},theme_limits={'科技':.2})
    assert r['holdings'][0]['action']=='暂停加仓'
    assert r['holdings'][0]['round_amount']==0
    assert r['theme_exposures'][0]['overweight'] is True
    without=plan_rebalance(holdings,{'甲':.5,'乙':.5})
    assert without['theme_exposures'][0]['limit'] is None
    assert without['holdings'][0]['round_amount']==50


def test_explicit_fund_targets_and_cent_sums():
    holdings=[row('a','甲',33.33,'核心宽基',fund_target=.4),row('b','乙',33.33,'核心宽基',fund_target=.4),row('c','丙',33.34,'卫星')]
    r=plan_rebalance(holdings,{'核心宽基':.8,'卫星':.2})
    assert sum(round(x['target_amount']*100) for x in r['holdings'])==10000
    assert [x['target_amount'] for x in r['holdings']]==[40,40,20]
    assert integer_sum(r['simulation'])==integer_sum(r['executable_simulation'])==10000


def test_fraction_and_threshold_configurable():
    r=plan_rebalance(standard(),{'卫星':.2,'核心宽基':.8},fraction=.5,threshold=.01)
    assert [h['round_amount'] for h in r['holdings']]==[-300,300]


@pytest.mark.parametrize('kwargs',[{'fraction':0},{'fraction':1.1},{'threshold':-1},{'threshold':1},{'theme_limits':{'科技':2}}])
def test_invalid_rule_parameters(kwargs):
    with pytest.raises(ValueError):plan_rebalance(standard(),{'卫星':.2,'核心宽基':.8},**kwargs)


@pytest.mark.parametrize('targets',[{'卫星':.2,'核心宽基':.7},{'卫星':-.1,'核心宽基':1.1},{'卫星':float('nan'),'核心宽基':1},{'卫星':20,'核心宽基':80}])
def test_invalid_targets_not_silently_normalized(targets):
    with pytest.raises(ValueError):plan_rebalance(standard(),targets)


@pytest.mark.parametrize('bad',[float('nan'),float('inf'),-1,True,'not numeric'])
def test_invalid_amounts(bad):
    holdings=standard();holdings[0]['amount']=bad
    with pytest.raises(ValueError):plan_rebalance(holdings,{'卫星':.2,'核心宽基':.8})


def test_duplicate_row_ids_and_unknown_buckets_fail():
    holdings=standard();holdings[1]['id']='s'
    with pytest.raises(ValueError):plan_rebalance(holdings,{'卫星':.2,'核心宽基':.8})
    with pytest.raises(ValueError):plan_rebalance(standard(),{'未知桶':1})
    with pytest.raises(ValueError):plan_rebalance([],{'甲':1})


def test_no_more_than_quarter_when_cent_rounding():
    holdings=[row('a','甲',.03,'甲'),row('b','乙',.01,'乙')]
    r=plan_rebalance(holdings,{'甲':.25,'乙':.75},threshold=0)
    assert all(abs(h['round_amount'])<=abs(h['final_adjustment_amount'])*.25+1e-9 for h in r['holdings'])
    assert integer_sum(r['simulation'])==4


def test_split_largest_remainders_exact_and_stable():
    assert split_cents(100,[1,1,1])==[34,33,33]
    assert split_cents(2,[1,1,1])==[1,1,0]
    assert split_cents(100,[])==[]


def test_fund_target_incomplete_or_invalid_rejected():
    holdings=standard();holdings[0]['fund_target']=.3
    with pytest.raises(ValueError):plan_rebalance(holdings,{'卫星':.2,'核心宽基':.8})
    holdings=[row('a','甲',50,'甲',fund_target=.5),row('b','乙',50,'甲')]
    with pytest.raises(ValueError):plan_rebalance(holdings,{'甲':1})


def test_explicit_future_redemption_date_overrides_claimed_free():
    holdings=standard();holdings[0]['earliest_redemption']='2099-01-01'
    r=plan_rebalance(holdings,{'卫星':.2,'核心宽基':.8})
    assert r['holdings'][0]['holding_status']=='locked'
    assert r['holdings'][0]['earliest_redemption']=='2099-01-01'
    assert all(x['executable_amount']==0 for x in r['holdings'])


@pytest.mark.parametrize('seed',range(15))
def test_financial_invariants_across_rounded_portfolios(seed):
    import random
    rng=random.Random(seed)
    holdings=[row(str(i),'基金'+str(i),Decimal(rng.randrange(0,100000))/100,'桶'+str(i%5),rng.choice(['free','locked','unknown'])) for i in range(10)]
    targets={'桶'+str(i):.2 for i in range(5)}
    result=plan_rebalance(holdings,targets)
    total=round(result['total_amount']*100)
    assert integer_sum(result['simulation'])==integer_sum(result['executable_simulation'])==total
    assert all(x['amount']>=0 for x in result['simulation']+result['executable_simulation'])
    assert sum(round(x['target_amount']*100) for x in result['holdings'])==total
    assert result['cash_reserve']>=0 and result['executable_cash_reserve']>=0
    for h in result['holdings']:
        assert abs(h['executable_amount'])<=abs(h['round_amount'])+1e-9
        assert abs(h['round_amount'])<=abs(h['final_adjustment_amount'])*.25+1e-9


def test_explicit_fund_targets_rebalance_inside_on_target_bucket():
    holdings=[row('a','甲',700,'核心宽基',fund_target=.5),row('b','乙',300,'核心宽基',fund_target=.5)]
    r=plan_rebalance(holdings,{'核心宽基':1})
    assert r['buckets'][0]['bucket_triggered'] is False
    assert r['buckets'][0]['fund_triggered'] is True
    assert [h['final_adjustment_amount'] for h in r['holdings']]==[-200,200]
    assert [h['round_amount'] for h in r['holdings']]==[-50,50]
    assert [h['executable_amount'] for h in r['holdings']]==[-50,50]
    assert [h['estimated_amount'] for h in r['holdings']]==[650,350]
    assert integer_sum(r['simulation'])==integer_sum(r['executable_simulation'])==100000
    assert all(any('基金层再平衡' in reason for reason in h['reasons']) for h in r['holdings'])


@pytest.mark.parametrize('first_amount,triggered',[(550,False),(551,True),(450,False),(449,True)])
def test_explicit_fund_target_exact_five_point_boundary(first_amount,triggered):
    holdings=[row('a','甲',first_amount,'核心宽基',fund_target=.5),row('b','乙',1000-first_amount,'核心宽基',fund_target=.5)]
    r=plan_rebalance(holdings,{'核心宽基':1})
    assert all(h['triggered'] is triggered for h in r['holdings'])
    assert r['buckets'][0]['triggered'] is triggered
    if not triggered:assert all(h['round_amount']==0 for h in r['holdings'])


def test_no_fund_target_does_not_invent_fund_level_rebalance():
    holdings=[row('a','甲',900,'核心宽基'),row('b','乙',100,'核心宽基')]
    r=plan_rebalance(holdings,{'核心宽基':1})
    assert all(h['round_amount']==0 for h in r['holdings'])
    assert r['buckets'][0]['triggered'] is False


@pytest.mark.parametrize('huge',['1e100','1e9999999',Decimal('9'*100)])
def test_huge_finite_money_reports_friendly_value_error(huge):
    holdings=standard();holdings[0]['amount']=huge
    with pytest.raises(ValueError,match='金额超出支持的分币计算精度'):
        plan_rebalance(holdings,{'卫星':.2,'核心宽基':.8})
