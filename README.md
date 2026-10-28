# ETF Market Monitor

本地 A股 ETF 每日体检、市场状态分析和个人仓位管理。Python 3.11 + Streamlit + SQLite + AKShare + Pandas + Plotly。

## 安装与启动

```bash
python3.11 -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell 使用 .venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

浏览器打开 `http://localhost:8501`。首页和五个页面：今日市场、ETF观察、市场宽度、我的组合、历史记录。
首次安装没有个人组合或行情；页面明确提示缺失，不展示模拟市场结论。SQLite 文件仅留在本地。

## 获取真实数据

在项目根目录、已激活虚拟环境中：

```bash
python -m jobs.update close --force
python -m jobs.update shares --force
python -m jobs.verify
```

收盘任务更新行情、四指数价格、估值、全A宽度，并保存市场/组合/建议快照。次日任务补充可验证的官方份额。
`--force` 绕过计划时间门槛，仍排除未完成日线，盘中宽度不能冒充收盘信号。
单一接口失败时保留缓存并继续；退出码1表示至少一个接口失败，详见日志和输出。当前深市份额未提供可靠日期，故份额命令可能返回1而系统仍正常可用。

自动调度和 Windows 任务计划步骤见 [docs/SCHEDULING.md](docs/SCHEDULING.md)。程序本身不是后台调度服务。

## 当前能力

- 七只观察ETF：510300、588000、159338、159915、159665、159992、518880；历史OHLC、成交量（份）、成交额（元）。
- SQLite去重、冲突/空值/OHLC/跳变校验、超时重试、东财与新浪备用源、缓存和交易日历校验。
- MA5/20/60、20/60日收益、60日收盘高点回撤、量比与趋势量能标签。
- 官方ETF份额1/5/20交易日变化、异常检测；官方指数PE/股息率及沪深300独立PE/PB历史补充源。
- 全A带时间戳快照、涨跌统计、完整性和涨跌停覆盖率；缺失MA宽度明确标注。
- 五维定性分析附原因；数据不完整时不提供方向结论。
- 六类资产配置、金额算仓位、目标偏离、超配优先风险提示；组合仅本地存储。
- 每日历史快照和7/30/90日/自定义查询。
- 下一交易日开盘执行的研究回测、费用、时间样本外及敏感性检查。

## 数据口径和限制

行情为未复权价格，跨拆分大幅跳变会被拒绝；回测不含分红，不等于总收益。
沪深300估值补充使用乐咕 TTM PE/PB月度历史，与中证官方PE1分别保留来源和定义，不混合计算百分位。
全A盘中采集并非同一秒；完整股票集合校验通过也不等于收盘数据。MA20/60全A覆盖、部分指数PB/历史估值、深市份额仍待补齐。
缺少历史五维时点数据时，风险策略回测明确不可用，不用当前值回填过去，也不以趋势单维冒充五维。
详情见 [FINAL_REPORT.md](FINAL_REPORT.md)、[docs/BACKTEST_REPORT.md](docs/BACKTEST_REPORT.md) 和 [TASKS.md](TASKS.md)。

## 本地配置与安全

变量名见 `.env.example`。程序直接读取环境变量，不自动加载 `.env`：

- `ETF_DB_PATH`：默认 `data/market.sqlite3`。
- `ETF_LOG_PATH`：默认 `logs/market.log`。
- `ETF_LOG_LEVEL`：默认 `INFO`。

不需要 AI API Key 即可运行；预留Key名称不代表必填。密钥、用户资产、数据库和日志不提交Git，不发送给第三方AI。损坏数据库保留原文件，应用提示修复，不自动删除或覆盖。

## 测试与研究报告

```bash
pytest -q
python -m jobs.backtest_report --calendar data/trading_calendar.csv --calendar-source "新浪公开交易日历（AKShare解码）"
```

pytest使用人工可验证、边界、失败和Mock数据；真实数据探测命令与单元测试分开。Python 3.11环境验收记录见最终报告。
项目只用于投资研究和风险管理，不自动交易，不保证收益或回撤。

## 四策略研究模块

```bash
python -m jobs.strategy_report
```

生成 `STRATEGY_REPORT.md` 以及 `reports/strategies/` 中的比较表、逐次决策、分段稳定性和净值/回撤HTML图。首页侧栏“策略研究”可查看规则试算和报告。

参数见 `config/strategies.json`：均线窗口、估值/宽度/量能阈值、仓位带、增仓步长和四策略风险仓上下限。仓位和百分位使用0—1小数；页面仓位输入使用百分比。修改参数后重新生成报告，不自动交易。

A长期价值配置、B纯趋势、C价值＋趋势、D卫星波段均输出原因。A/C历史回测要求逐日可审计的PE/PB分位及发布时间，C还需要市场宽度及发布时间；不将当前估值回填过去。可以通过 `jobs.strategy_report.build_comparison` 向行情DataFrame提供 `pe_percentile`、`pb_percentile`、`valuation_available_at`、`breadth_ratio`、`breadth_available_at`，可选 `shares_change5`/`shares_available_at`。发布时间按上海时区判断，不晚于信号日收盘决策截止时间。

当前数据库缺少完整历史时点因子，因此A/C会显示“历史数据不足”，而不是生成虚构收益。B与简单宽基/现金比较，D与同卫星额度比较；不能以较低风险额度的回撤直接证明择时有效。

## Excel持仓再平衡

侧栏打开“持仓再平衡”，上传当前基金总账 `.xlsx`，无需把文件放入Git。支持“当前持仓＋目标组合”，目标比例优先读取可编辑列。默认偏离超过±5个百分点触发，分批取目标差额的25%。页面区分最终差额、理论本轮计划、已确认资金支持的金额及模拟仓位；赎回限制缺失必须人工确认，不自动下单。操作后更新原表再上传。字段、资金与分摊规则见 [docs/REBALANCE.md](docs/REBALANCE.md)。

## 部署指南

Windows首次安装、启动、数据更新、自动任务、备份和常见问题见 [DEPLOYMENT.md](DEPLOYMENT.md)。
