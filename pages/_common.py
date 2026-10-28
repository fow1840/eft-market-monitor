"""Rendering helpers. Reads cached local data only; no network on rerender."""
from datetime import datetime
from zoneinfo import ZoneInfo
import sqlite3
import pandas as pd
import streamlit as st
from config import load_settings
from src.storage import initialize_database
from src.logging_setup import configure_logging

DIMENSION_NAMES = {'trend': '趋势', 'volume': '成交量', 'shares': 'ETF份额', 'valuation': '估值', 'breadth': '市场宽度'}


def setup(title):
    st.set_page_config(page_title=title, page_icon='📊', layout='wide')
    st.title(title)
    st.caption('上海时间：' + datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M'))
    try:
        settings = load_settings()
        configure_logging(settings.log_path, settings.log_level)
        initialize_database(settings.db_path)
        return settings.db_path
    except (ValueError, OSError, sqlite3.Error):
        st.error('初始化失败，请检查本地配置、数据库权限和日志目录。')
        st.stop()


def dashboard(path):
    from src.dashboard import build_dashboard
    try:
        return build_dashboard(path)
    except (ValueError, OSError, sqlite3.Error):
        st.warning('本地数据读取失败。请检查日志和数据库；未生成市场判断。')
        return {'market': {'state': '中性', 'complete': False, 'reasons': ['本地数据读取失败']}, 'warnings': []}


def show_dimensions(data):
    columns = st.columns(5)
    for column, (key, name) in zip(columns, DIMENSION_NAMES.items()):
        dimension = data.get(key, {}) or {}
        if isinstance(dimension, str):
            dimension = {'state': dimension}
        state = dimension.get('state') or dimension.get('trend') or dimension.get('volume_state') or '数据不足'
        if dimension.get('available') is False:
            state = '数据不足'
        column.metric(name, state)
        if dimension.get('date'):
            column.caption(str(dimension['date']))
        if dimension.get('source'):
            column.caption(str(dimension['source']))
    market = data.get('market', {})
    complete = market.get('complete', False)
    st.subheader('五维市场状态：' + str(market.get('state', '中性')))
    if not complete:
        st.warning('五维数据不完整，暂不作方向性判断；中性不代表低风险。组合规则将按“数据不足”处理。')
    for reason in market.get('reasons', []):
        st.write('• ' + str(reason))
    for warning in data.get('warnings', []):
        st.warning(str(warning))


def portfolio_view(path, market):
    from src.history import load_portfolio
    from src.portfolio import analyze_portfolio, risk_advice
    rows = load_portfolio(path)
    if not rows:
        st.info('尚未录入组合。请前往“我的组合”添加资产和目标配置。')
        return
    try:
        result = analyze_portfolio(rows)
    except ValueError as exc:
        st.warning(str(exc))
        return
    st.metric('组合总金额（元）', f"{result['total_amount']:,.2f}")
    st.dataframe(result['holdings'], hide_index=True, width='stretch')
    categories = result['categories'].copy()
    state = market.get('state', '中性') if market.get('complete') else '数据不足'
    advice = [risk_advice(row.current_pct, row.target_pct, state) for row in categories.itertuples()]
    categories['建议'] = [item['action'] for item in advice]
    categories['原因'] = [item['reason'] for item in advice]
    st.dataframe(categories, hide_index=True, width='stretch')
    st.bar_chart(categories.set_index('category')[['current_pct', 'target_pct']])
    st.caption('仓位单位为百分比，偏离单位为百分点。默认绝对偏离超过5个百分点触发再平衡提醒。')
