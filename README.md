# ETF Market Monitor

本地 A股 ETF 研究与风险管理系统，开发进度见 TASKS.md。

## 启动

需要 Python 3.11。在项目目录执行：

```bash
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

配置通过环境变量读取；变量名称见 `.env.example`，程序不自动加载 `.env`。
默认 SQLite 位于 `data/market.sqlite3`，轮转日志位于 `logs/market.log`。
不提交本地数据库、日志和秘密。无需 AI API Key 即可启动。

```bash
pytest
```

当前提供首页、配置、数据库初始化与日志基础设施；金融数据模块尚待实现。
