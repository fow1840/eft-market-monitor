import streamlit as st
from pages._common import setup, dashboard

path = setup('市场宽度')
breadth = dashboard(path).get('breadth', {}) or {}
if not breadth.get('available', False):
    st.warning('全A宽度数据不可用或不完整，不能用局部样本代替全市场。')
else:
    st.metric('宽度状态', breadth.get('state', '数据不足'))
if breadth.get('date'):
    st.write('数据日期：', breadth['date'])
if breadth.get('source'):
    st.caption('来源：' + str(breadth['source']))
values = {key: value for key, value in breadth.items() if key not in ('reasons', 'source', 'available')}
if values:
    st.json(values)
for reason in breadth.get('reasons', []):
    st.write(str(reason))
st.caption('涨跌停以个股板块、ST标记与有效涨跌停价为准；MA覆盖率需足够历史数据。')
