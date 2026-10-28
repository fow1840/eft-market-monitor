"""Private, in-memory ledger import and deterministic staged rebalance."""
import json
from io import BytesIO
import pandas as pd
import streamlit as st
from pages._common import setup
from src.holdings_excel import parse_holdings_excel
from src.rebalance import plan_rebalance
from src.export_utils import safe_excel_csv

setup('持仓再平衡')
st.caption('上传更新后的基金持仓总账重新分析。金额由规则计算，不调用AI生成金额，不自动下单。文件只在本次页面会话内分析。')
upload=st.file_uploader('上传基金持仓总账（.xlsx）',type=['xlsx'])
c1,c2=st.columns(2)
threshold=c1.number_input('偏离阈值（百分点）',min_value=0.,max_value=100.,value=5.,step=1.)/100
fraction=c2.number_input('本轮执行目标调整量（%）',min_value=1.,max_value=100.,value=25.,step=5.)/100
with st.expander('可选主题上限'):
    st.caption('JSON格式，比例使用0—1。未配置主题不擅自设定独立上限，仍检查重复、重叠及所属资产桶超配。')
    raw_limits=st.text_area('主题上限JSON','{}',key='rebalance_theme_limits')
if upload is None:
    st.info('支持现有“当前持仓＋目标组合”格式；目标优先读取“目标比例（可编辑）”列。缺少赎回信息时标记需人工确认。')
    st.stop()
if upload.size>10*1024*1024:
    st.error('文件超过10MB，请保留所需表格后重试。');st.stop()
try:
    limits=json.loads(raw_limits)
    if not isinstance(limits,dict):raise ValueError('主题上限必须为JSON对象')
    imported=parse_holdings_excel(BytesIO(upload.getvalue()))
    result=plan_rebalance(imported['holdings'],imported['targets'],fraction=fraction,threshold=threshold,theme_limits=limits)
except (ValueError,TypeError,KeyError) as exc:
    st.error(f'无法分析：{exc}');st.stop()

LABELS={'id':'行标识','name':'基金名称','account':'账户','bucket':'资产桶','themes':'主题/重叠组',
 'current_amount':'当前金额(元)','current_weight':'当前占比','target_amount':'最终目标金额(元)',
 'target_weight':'最终目标占比','deviation_pp':'偏离(百分点)','final_adjustment_amount':'最终目标调整额(元)',
 'desired_round_amount':'本轮25%原始计划额(元)','round_amount':'本轮资金平衡计划额(元)',
 'executable_amount':'已确认条件下本轮金额(元)','action':'建议动作','holding_status':'赎回确认状态',
 'holding_period':'持有期','earliest_redemption':'最早赎回日','theme':'主题','limit':'主题上限','overweight':'主题超配','restriction_reason':'限制/确认说明','estimated_amount':'本轮理论调仓后金额(元)',
 'estimated_weight':'本轮理论调仓后占比','executable_estimated_amount':'已确认模拟金额(元)',
 'executable_estimated_weight':'已确认模拟占比','amount':'金额(元)','weight':'占比','reasons':'原因','triggered':'超出阈值','bucket_triggered':'资产桶触发','fund_triggered':'基金目标触发'}
LABELS['desired_round_amount']=f'本轮{fraction:.0%}计划额（阈值/主题约束后，元）'

def table(rows,columns=None):
    frame=pd.DataFrame(rows)
    if columns:frame=frame[[x for x in columns if x in frame.columns]]
    for key in ('reasons','themes'):
        if key in frame:frame[key]=frame[key].map(lambda x:'；'.join(map(str,x)) if isinstance(x,list) else str(x))
    for key in frame.columns:
        if key.endswith('_weight') or key in ('weight','limit'):
            frame[key]=frame[key].map(lambda x:'未配置' if x is None or pd.isna(x) else f'{float(x):.2%}')
    if 'holding_status' in frame:frame['holding_status']=frame.holding_status.map(lambda x:{'free':'已确认可赎回','locked':'受限','unknown':'需人工确认'}.get(x,x))
    st.dataframe(frame.rename(columns=LABELS),hide_index=True,width='stretch')
    return frame

st.metric('当前总资产（元）',f"{result['total_amount']:,.2f}")
for warning in [*imported.get('warnings',[]),*result.get('warnings',[])]:st.warning(str(warning))
st.subheader('当前组合、目标组合与超配/低配')
buckets=pd.DataFrame(result['buckets'])
table(result['buckets'])
if not buckets.empty:st.bar_chart((buckets.set_index('bucket')[['current_weight','target_weight']]*100).rename(columns={'current_weight':'当前占比(%)','target_weight':'目标占比(%)'}))
st.subheader('每只基金建议动作与本轮金额')
st.caption('正数为买入，负数为减仓。最终目标差额与本轮分批金额分别列示；无单基金目标时，仅按桶内当前金额比例分摊，不替你挑选基金。')
frame=table(result['holdings'],['id','account','name','bucket','current_amount','current_weight','target_amount','final_adjustment_amount','action','desired_round_amount','round_amount','executable_amount','holding_status','holding_period','earliest_redemption','restriction_reason','estimated_weight','executable_estimated_weight','reasons'])
if result.get('theme_exposures'):
    with st.expander('主题集中度与重叠检查'):table(result['theme_exposures'])
st.caption('金额按全组合汇总，跨账户资金调拨仍需人工核对；保守模拟不是账户级可用余额。')
st.warning('理论计划不代表可以立即成交。未确认持有期/赎回限制的减仓不能用于已确认资金预算；即使已标可赎回，也需人工核实到账时间、费用和交易规则。')
a,b=st.tabs(['本轮理论计划后的模拟组合','仅已确认条件支持的模拟组合'])
with a:
    table(result['simulation'])
    st.write('理论剩余待分配现金（元）：',result['cash_reserve'])
with b:
    table(result['executable_simulation'])
    st.write('已确认模拟剩余待分配现金（元）：',result['executable_cash_reserve'])
for assumption in result.get('assumptions',[]):st.caption(str(assumption))
st.download_button('下载本轮分析CSV（含个人持仓，请自行保管）',safe_excel_csv(frame.rename(columns=LABELS)),file_name='持仓再平衡分析.csv',mime='text/csv')
st.info('实际操作后，更新Excel的当前金额与限制字段，再上传重新分析。刷新分析不会执行交易。')
