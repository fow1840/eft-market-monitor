import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo
import streamlit as st
from config import load_settings
from src.storage import initialize_database
from src.logging_setup import configure_logging

st.set_page_config(page_title='ETF 每日体检', page_icon='📊', layout='wide')
st.title('ETF Market Monitor')
st.caption('A股 ETF 每日体检 · 市场状态 · 个人仓位管理')
st.write('上海时间：', datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M'))
try:
    settings = load_settings()
    logger = configure_logging(settings.log_path, settings.log_level)
    initialize_database(settings.db_path)
except (ValueError, OSError, sqlite3.Error):
    st.error('初始化失败，请检查本地配置、数据库权限和日志目录。')
    st.stop()
st.success('本地数据库已就绪')
st.info('行情数据尚未更新。后续模块将显示数据来源、交易日期和风险分析。')
st.caption('用于投资研究与风险管理，不自动交易，不承诺收益。')
