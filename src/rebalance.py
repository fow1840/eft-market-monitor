"""Cent-exact local rebalancing. No model-generated amounts or order execution.

Bucket targets are authoritative. Without fund targets, each bucket's target is
allocated pro rata to its existing funds; this is arithmetic, not fund selection.
Unknown/locked redemptions never finance executable purchases. Cash remaining
from proposed sales is a separate, explicit unallocated cash position.
"""
from collections import defaultdict
from decimal import Decimal, DecimalException, ROUND_HALF_UP, ROUND_FLOOR
import unicodedata
from datetime import date, datetime
from zoneinfo import ZoneInfo

D = Decimal


def number(value, label):
    if isinstance(value, bool): raise ValueError(f'{label}必须为有限数值')
    try: result = D(str(value))
    except Exception: raise ValueError(f'{label}必须为有限数值') from None
    if not result.is_finite(): raise ValueError(f'{label}必须为有限数值')
    return result


def cents(value):
    try:
        return int((number(value, '金额') * 100).quantize(D('1'), rounding=ROUND_HALF_UP))
    except DecimalException:
        raise ValueError('金额超出支持的分币计算精度，请检查Excel中的单位或数值') from None


def split_cents(total, weights):
    """Largest remainder allocation: exact sum, stable row-order tie break."""
    weights = [number(x, '分配权重') for x in weights]
    if total < 0 or any(x < 0 for x in weights): raise ValueError('分配不可为负')
    if not weights: return []
    denominator = sum(weights)
    if denominator == 0: weights = [D(1)] * len(weights); denominator = D(len(weights))
    exact = [D(total) * x / denominator for x in weights]
    result = [int(x.to_integral_value(rounding=ROUND_FLOOR)) for x in exact]
    order = sorted(range(len(weights)), key=lambda i: (-(exact[i]-result[i]),i))
    for i in order[:total-sum(result)]: result[i] += 1
    return result


def _money(value): return float(D(value)/100)


def plan_rebalance(holdings, targets, fraction=.25, threshold=.05, theme_limits=None):
    fraction=number(fraction,'本轮比例');threshold=number(threshold,'偏离阈值')
    if not 0 < fraction <= 1 or not 0 <= threshold < 1: raise ValueError('比例或阈值越界')
    targets={str(k).strip():number(v,'目标仓位') for k,v in targets.items()}
    if not targets or any(not k or not 0<=v<=1 for k,v in targets.items()) or abs(sum(targets.values())-1)>D('0.000000001'):
        raise ValueError('目标仓位必须在0到1且合计100%，不自动归一化')
    rows=[];ids=set();warnings=[];groups=defaultdict(list)
    aliases={'可赎回':'free','受限':'locked','需人工确认':'unknown','free':'free','locked':'locked','unknown':'unknown'}
    for index,item in enumerate(holdings):
        row=dict(item); name=str(row.get('name') or '').strip();bucket=str(row.get('bucket') or '').strip()
        identity=str(row.get('id',index));amount=cents(row.get('amount'))
        if not name or bucket not in targets:raise ValueError('基金名称或资产桶目标缺失')
        if amount<0 or identity in ids:raise ValueError('金额不可为负且持仓行ID必须唯一')
        ids.add(identity)
        themes=row.get('themes') or []
        if isinstance(themes,str):themes=[themes]
        if not isinstance(themes,(list,tuple)) or any(not isinstance(x,str) for x in themes):raise ValueError('主题必须为字符串列表')
        row.update(id=identity,name=name,bucket=bucket,amount_cents=amount,
                   themes=list(dict.fromkeys(x.strip() for x in themes if x.strip())),
                   holding_status=aliases.get(row.get('holding_status'),'unknown'),virtual=False)
        if row.get('earliest_redemption'):
            try: redemption=date.fromisoformat(str(row['earliest_redemption'])[:10])
            except ValueError: raise ValueError('最早赎回日期格式无效') from None
            if redemption>datetime.now(ZoneInfo('Asia/Shanghai')).date():row['holding_status']='locked'
        rows.append(row)
        key=''.join(unicodedata.normalize('NFKC',name).split()).casefold()
        groups[key].append(identity)
    total=sum(row['amount_cents'] for row in rows)
    if total<=0:raise ValueError('组合总金额必须大于零')
    for group in groups.values():
        if len(group)>1:warnings.append('重复基金跨行/跨账户：'+','.join(group)+'；金额汇总但不自动删除合法持仓')
    limits={str(k):number(v,'主题上限') for k,v in (theme_limits or {}).items()}
    if any(not 0<=v<=1 for v in limits.values()):raise ValueError('主题上限必须在0到1')
    theme_totals=defaultdict(int)
    for row in rows:
        for theme in row['themes']:theme_totals[theme]+=row['amount_cents']
    overthemes={k for k,v in limits.items() if D(theme_totals[k])/total>v}
    for theme in sorted(overthemes):warnings.append(f'主题超配：{theme}，暂停该主题新增；重叠主题金额不能相加作为总资产')
    for theme,amount in theme_totals.items():
        if theme not in limits and sum(theme in r['themes'] for r in rows)>1:
            warnings.append(f'主题重叠：{theme}；未配置独立主题上限，不推断为超配')
    bucket_targets=split_cents(total,list(targets.values()))
    bucket_rows=[]
    for (bucket,target),target_amount in zip(targets.items(),bucket_targets):
        selected=[row for row in rows if row['bucket']==bucket]
        if not selected and target_amount:
            selected=[dict(id='virtual:'+bucket,name='待指定基金',account='',bucket=bucket,amount_cents=0,themes=[],holding_status='unknown',virtual=True)]
            rows.extend(selected)
        current=sum(row['amount_cents'] for row in selected);delta=target_amount-current
        active=abs(D(current)/total-target)>threshold
        if '核心' in bucket and D(current)/total<target-threshold:warnings.append('核心仓低配：'+bucket)
        explicit=[row.get('fund_target') for row in selected]
        if any(x is not None for x in explicit):
            if any(x is None for x in explicit):raise ValueError('同桶基金目标必须全部填写或全部留空')
            weights=[number(x,'基金目标') for x in explicit]
            if any(x<0 for x in weights) or abs(sum(weights)-target)>D('0.000000001'):raise ValueError('基金目标合计必须等于资产桶目标')
        else:
            if current == 0 and len(selected) > 1:raise ValueError('零持仓桶的多只基金需明确基金目标比例')
            weights=[row['amount_cents'] for row in selected]
        amounts=split_cents(target_amount,weights)
        # Round at bucket level, then distribute unsigned fund changes coherently.
        changes=[amount-row['amount_cents'] for row,amount in zip(selected,amounts)]
        explicit_targets=any(x is not None for x in explicit)
        fund_triggers=[explicit_targets and abs(D(change)/total)>threshold for change in changes]
        row_triggers=[active or flag for flag in fund_triggers]
        desired=[int((D(abs(change))*fraction).quantize(D('1'),rounding=ROUND_FLOOR))*(1 if change>=0 else -1) if triggered else 0 for change,triggered in zip(changes,row_triggers)]
        for row,amount,change,proposal,row_active in zip(selected,amounts,changes,desired,row_triggers):
            reasons=['桶内目标按现有金额比例分配；不是基金优选'] if not any(x is not None for x in explicit) else ['使用明确的基金目标比例']
            if proposal>0 and any(theme in overthemes for theme in row['themes']):proposal=0;reasons.append('主题超配优先，暂停新增')
            if row_active and not active:reasons.append('资产桶整体未超阈值，但明确的基金目标偏离超过阈值，触发基金层再平衡')
            if not row_active:reasons.append('资产桶和适用基金目标偏离未超过阈值，保持；超配时暂停加仓')
            row.update(target_cents=amount,final_delta_cents=change,desired_cents=proposal,reasons=reasons,active=row_active,explicit_target=explicit_targets)
        bucket_rows.append(dict(bucket=bucket,current_amount=_money(current),target_amount=_money(target_amount),current_weight=float(D(current)/total),target_weight=float(target),deviation_pp=float((D(current)/total-target)*100),final_adjustment_amount=_money(delta),triggered=active or any(fund_triggers),bucket_triggered=active,fund_triggered=any(fund_triggers)))
    sell_total=sum(-r['desired_cents'] for r in rows if r['desired_cents']<0)
    buyers=[r for r in rows if r['desired_cents']>0]
    requested_buys=sum(r['desired_cents'] for r in buyers)
    funded=split_cents(min(requested_buys,sell_total),[r['desired_cents'] for r in buyers])
    for row in rows:row['round_cents']=min(0,row['desired_cents'])
    for row,value in zip(buyers,funded):row['round_cents']=value
    executable_sell=sum(-r['round_cents'] for r in rows if r['round_cents']<0 and r['holding_status']=='free')
    eligible=[r for r in rows if r['round_cents']>0 and not r['virtual']]
    executable_buys=split_cents(min(executable_sell,sum(r['round_cents'] for r in eligible)),[r['round_cents'] for r in eligible])
    for row in rows:row['executable_cents']=row['round_cents'] if row['round_cents']<0 and row['holding_status']=='free' else 0
    for row,value in zip(eligible,executable_buys):row['executable_cents']=value
    reserve=-sum(r['round_cents'] for r in rows)
    executable_reserve=-sum(r['executable_cents'] for r in rows)
    public=[];simulation=[];executable_simulation=[]
    for row in rows:
        amount=row['amount_cents'];round_amount=row['round_cents'];execute=row['executable_cents']
        restriction={'free':'可赎回（仍需核对实际到账、费用和交易规则）','locked':'受限，禁止将赎回款作为本轮可用资金','unknown':'需人工确认持有期/赎回限制'}[row['holding_status']]
        action='买入多少' if round_amount>0 and not row['virtual'] else '减仓多少' if round_amount<0 else '暂停加仓' if row['final_delta_cents']<0 or row['desired_cents']>0 or row['virtual'] or any(t in overthemes for t in row['themes']) else '保持'
        if row['virtual']:row['reasons'].append('该桶无现有基金，需人工指定；仅显示桶级资金意向，不构造基金推荐')
        if row['desired_cents']>round_amount:row['reasons'].append('卖出预算不足，本轮买入按可筹资金缩减；不假设新增资金')
        row['reasons'].append(restriction)
        if execute!=round_amount:row['reasons'].append('含未确认/受限赎回或未指定基金：理论计划不是可直接执行金额')
        public.append(dict(id=row['id'],name=row['name'],account=row.get('account',''),bucket=row['bucket'],themes=row['themes'],current_amount=_money(amount),current_weight=float(D(amount)/total),target_amount=_money(row['target_cents']),target_weight=float(D(row['target_cents'])/total),final_adjustment_amount=_money(row['final_delta_cents']),desired_round_amount=_money(row['desired_cents']),round_amount=_money(round_amount),executable_amount=_money(execute),action=action,holding_status=row['holding_status'],restriction=restriction,restriction_reason=row.get('restriction_reason',''),holding_period=row.get('holding_period',''),earliest_redemption=row.get('earliest_redemption'),virtual=row['virtual'],triggered=row['active'],explicit_target=row['explicit_target'],reasons=row['reasons'],estimated_amount=_money(amount+round_amount),estimated_weight=float(D(amount+round_amount)/total),executable_estimated_amount=_money(amount+execute),executable_estimated_weight=float(D(amount+execute)/total)))
        simulation.append(dict(id=row['id'],name=row['name'],bucket=row['bucket'],amount=_money(amount+round_amount),weight=float(D(amount+round_amount)/total)))
        executable_simulation.append(dict(id=row['id'],name=row['name'],bucket=row['bucket'],amount=_money(amount+execute),weight=float(D(amount+execute)/total)))
    if reserve:simulation.append(dict(id='reserve',name='待分配现金',bucket='待分配现金',amount=_money(reserve),weight=float(D(reserve)/total)))
    if executable_reserve:executable_simulation.append(dict(id='reserve',name='待分配现金',bucket='待分配现金',amount=_money(executable_reserve),weight=float(D(executable_reserve)/total)))
    if any(r['holding_status']=='unknown' for r in rows if not r['virtual']):warnings.append('部分基金持有期/赎回限制需人工确认；理论减仓金额不代表当前可赎回')
    if requested_buys>sell_total:warnings.append('触发阈值后的买入需求高于卖出预算，已按资金约束缩减本轮买入')
    return dict(total_amount=_money(total),fraction=float(fraction),threshold_pp=float(threshold*100),buckets=bucket_rows,holdings=public,simulation=simulation,executable_simulation=executable_simulation,warnings=warnings,theme_exposures=[dict(theme=k,amount=_money(v),weight=float(D(v)/total),limit=float(limits[k]) if k in limits else None,overweight=k in overthemes) for k,v in theme_totals.items()],cash_reserve=_money(reserve),executable_cash_reserve=_money(executable_reserve),requested_buy_amount=_money(requested_buys),planned_sell_amount=_money(sell_total),executable_sell_amount=_money(executable_sell),funding_shortfall=_money(max(0,requested_buys-sell_total)),assumptions=['固定总资产，不假设外部新增资金；先卖后买，赎回到账前不能实际买入','模拟未计手续费、税费、价格波动；现金余额不等于真实账户可用余额','本轮金额是最终目标差额的配置比例；阈值和资金约束可进一步缩减','市场趋势信号不参与金额计算；解释由规则模板生成，不调用LLM'])
