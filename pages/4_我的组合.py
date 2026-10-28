import streamlit as st
import pandas as pd
from pages._common import setup, dashboard, portfolio_view
from src.portfolio import CATEGORIES, analyze_portfolio
from src.history import load_portfolio, save_portfolio

path = setup('我的组合')
st.caption('仅保存在本机 SQLite。金额单位为元；目标仓位填写0到100，合计须为100，现金也须纳入。当前仓位由金额计算。')
rows = load_portfolio(path)
frame = pd.DataFrame(rows, columns=['name', 'amount', 'category', 'target_pct'])
with st.form('portfolio_editor'):
    edited = st.data_editor(frame, num_rows='dynamic', hide_index=True, width='stretch', column_config={
        'name': st.column_config.TextColumn('基金/资产名称', required=True),
        'amount': st.column_config.NumberColumn('金额（元）', min_value=0.0, required=True),
        'category': st.column_config.SelectboxColumn('资产类型', options=list(CATEGORIES), required=True),
        'target_pct': st.column_config.NumberColumn('目标仓位（%）', min_value=0.0, max_value=100.0, required=True),
    })
    submitted = st.form_submit_button('验证并保存组合')
if submitted:
    try:
        records = edited.to_dict('records')
        analyze_portfolio(records)
        save_portfolio(path, records)
        st.success('组合已保存')
    except (ValueError, TypeError) as exc:
        st.error(str(exc))
portfolio_view(path, dashboard(path).get('market', {}))
