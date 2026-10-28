import streamlit as st
from pages._common import setup, dashboard, show_dimensions, portfolio_view

path = setup('ETF Market Monitor')
st.caption('A股 ETF 每日体检 · 市场状态 · 个人仓位管理')
st.success('本地数据库已就绪')
data = dashboard(path)
st.subheader('沪深300 · 510300')
show_dimensions(data)
st.subheader('当前组合与今日风险提示')
portfolio_view(path, data.get('market', {}))
st.info('行情更新：前往“ETF观察”手动更新，或按 README 执行收盘/次日任务。页面刷新只读取本地缓存。')
st.caption('用于投资研究与风险管理，不自动交易，不承诺收益。')
