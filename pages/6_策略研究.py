"""Local strategy research; renders closed-bar rules and generated report only."""
import json
from pathlib import Path
import streamlit as st
from pages._common import setup
from src.market_data import ETF_UNIVERSE,read_quotes
from src.strategies import load_config,validate_config,make_features,evaluate

path=setup('策略研究')
st.caption('规则研究与风险收益比较；T日收盘信号最早用于T+1，不调用LLM预测。')
strategy=st.selectbox('策略',['A','B','C','D'],format_func=lambda x:{'A':'A 长期价值配置','B':'B 纯趋势','C':'C 价值＋趋势','D':'D 卫星仓波段'}[x])
symbol=st.selectbox('观察ETF',list(ETF_UNIVERSE),format_func=lambda x:f'{x} {ETF_UNIVERSE[x]}')
weight=st.number_input('该标的当前占整个组合的比例（%）',min_value=0.,max_value=100.,value=0.)/100
with st.expander('可配置规则（修改仅用于本页试算）'):
    raw=st.text_area('JSON参数',json.dumps(load_config(),ensure_ascii=False,indent=2),height=300)
try:
    config=validate_config(json.loads(raw))
    data=read_quotes(path,symbol)
    if data.empty:st.info('没有本地行情，请先更新。')
    else:
        row=make_features(data,config).iloc[-1].to_dict()
        decision=evaluate(strategy,row,weight,config)
        st.caption(f"日线日期：{row['date']}；目标占比按整个组合计算。")
        st.metric('状态',decision['state']);st.metric('操作',decision['action'])
        st.write(f"建议风险仓目标：{decision['target_weight']:.1%}")
        for reason in decision['reasons']:st.write(reason)
        if strategy in ('A','C'):st.warning('本页没有注入可审计的历史因子发布时间；A/C确认不足会暂停新增，不能把当前估值冒充历史数据。')
except (ValueError,KeyError,TypeError) as exc:st.error(f'参数或数据校验失败：{exc}')
report=Path(__file__).resolve().parents[1]/'STRATEGY_REPORT.md'
if report.exists():
    st.subheader('已生成的研究报告')
    st.markdown(report.read_text())
    st.download_button('下载策略报告',report.read_bytes(),file_name=report.name)
    chart=report.parent/'reports'/'strategies'/'nav_drawdown.html'
    if chart.exists():st.download_button('下载净值与回撤图（浏览器打开）',chart.read_bytes(),file_name=chart.name,mime='text/html')
