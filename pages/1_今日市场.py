import streamlit as st
from pages._common import setup, dashboard, show_dimensions

path = setup('今日市场')
data = dashboard(path)
st.write('观察标的：沪深300ETF（510300）')
show_dimensions(data)
st.caption('各维度保留各自观察日期；不同交易日的数据不得直接视为同步信号。')
