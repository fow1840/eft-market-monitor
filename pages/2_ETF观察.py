import streamlit as st
import plotly.express as px
from pages._common import setup
from src.market_data import ETF_UNIVERSE, read_quotes, update_quotes
from src.indicators import calculate_indicators

path = setup('ETF 观察')
symbol = st.selectbox('ETF', list(ETF_UNIVERSE), format_func=lambda x: f'{x} {ETF_UNIVERSE[x]}')
if st.button('更新行情'):
    with st.spinner('正在请求行情；失败时使用已有缓存'):
        result = update_quotes(path, symbol, force=True)
    if result['error']:
        st.warning(result['error'])
try:
    data = read_quotes(path, symbol)
except Exception:
    st.error('行情缓存读取失败，请检查数据库和日志。')
    st.stop()
if data.empty:
    st.info('本地尚无行情，请点击更新行情。')
else:
    st.caption(f"来源 {data.source.iloc[-1]} · 最新交易日 {data.date.max().date()} · {len(data)}条 · 未复权 · 成交量：份；成交额：元")
    if len(data) < 250:
        st.warning('历史数据少于250个交易日，相关长期分析可能不可用。')
    try:
        indicators = calculate_indicators(data)
        latest = indicators.iloc[-1]
        col1, col2 = st.columns(2)
        col1.metric('趋势', latest.trend)
        col2.metric('量能', latest.volume_state)
        st.plotly_chart(px.line(indicators, x='date', y=['close', 'ma5', 'ma20', 'ma60'], title='收盘价与移动平均线'), width='stretch')
        st.dataframe(indicators.sort_values('date', ascending=False), hide_index=True, width='stretch')
    except ValueError as exc:
        st.warning(f'数据校验未通过，不生成指标：{exc}')
    st.download_button('下载本地行情 CSV', data.to_csv(index=False).encode('utf-8-sig'), file_name=f'{symbol}.csv')
