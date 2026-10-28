from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import streamlit as st
from pages._common import setup
from src.history import query_snapshots

path = setup('历史记录')
today = datetime.now(ZoneInfo('Asia/Shanghai')).date()
window = st.selectbox('查询区间', ['最近7天', '最近30天', '最近90天', '自定义日期'])
if window == '自定义日期':
    start = st.date_input('开始日期', today - timedelta(days=30))
    end = st.date_input('结束日期', today)
else:
    days = {'最近7天': 7, '最近30天': 30, '最近90天': 90}[window]
    start, end = today - timedelta(days=days - 1), today
if start > end:
    st.error('开始日期不能晚于结束日期。')
else:
    snapshots = query_snapshots(path, start.isoformat(), end.isoformat())
    if not snapshots:
        st.info('所选区间暂无每日记录。运行每日更新任务后会保存快照。')
    for snapshot in snapshots:
        with st.expander(str(snapshot['date'])):
            st.json(snapshot['payload'])
