# 设计决定
- 使用 Python 3.11 + Streamlit + SQLite + AKShare + Pandas + Plotly + pytest。
- 本地研究和风险管理，不自动交易。
- 行情与信号保留来源、日期，缺失值不伪造，不以当前数据回填历史回测。
- SQLite 和本地缓存不提交；API Key 仅环境注入。
