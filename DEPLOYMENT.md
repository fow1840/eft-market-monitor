# ETF Market Monitor 部署与运行指南

适用于个人 Windows 10/11 电脑。本程序运行在自己的电脑上，通过浏览器访问；无需购买服务器，也不需要 AI API Key。

## 1. 安装准备

安装以下软件：

- Python **3.11**：https://www.python.org/downloads/ 。安装时勾选 **Add Python to PATH**。
- Git：https://git-scm.com/downloads 。默认选项安装即可。

安装后重新打开 PowerShell，检查：

```powershell
py -3.11 --version
git --version
```

## 2. 下载项目

以下以 `C:\ETF` 为部署目录：

```powershell
New-Item -ItemType Directory -Force C:\ETF | Out-Null
Set-Location C:\ETF
git clone https://github.com/fow1840/eft-market-monitor.git
Set-Location C:\ETF\eft-market-monitor
```

如果此前已经下载过，不要重复 clone，直接进入原项目目录。

## 3. 安装依赖

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

上述命令直接调用虚拟环境内的 Python，**无需激活虚拟环境，也不需要修改 PowerShell 执行策略**。
需要精确复现开发验收的依赖版本时，可以将最后一行替换为：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
```

锁定版本来自 Linux 验收环境，尚未逐个验证 Windows 包的可安装性；Windows 优先使用 `requirements.txt`。

## 4. 首次更新真实数据

```powershell
.\.venv\Scripts\python.exe -m jobs.update close --force
.\.venv\Scripts\python.exe -m jobs.update shares --force
.\.venv\Scripts\python.exe -m jobs.verify
```

网络请求可能需要数分钟。`--force` 用于手动初始化或重试，不受计划时间门槛限制；它不会把当天未收盘日线当成完整行情。

数据保存在项目目录 `data\market.sqlite3`，日志保存在 `logs\market.log`。部分来源失败或字段缺失时，程序保留已有数据并标注不可用；不要把这理解为所有数据都更新成功。命令非零退出时，检查输出与日志。

当前深市份额、部分指数历史估值和全A均线覆盖尚有缺口。盘中宽度不能作为收盘信号，详细限制见 `FINAL_REPORT.md`。

## 5. 启动程序

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1
```

浏览器打开：**http://127.0.0.1:8501** 。

保持 PowerShell 窗口打开；按 `Ctrl+C` 停止程序。不要将个人持仓页面开放到公网。默认本地使用不需要账号密码。

侧栏包括市场页面、我的组合、策略研究和持仓再平衡。首次没有组合时，可手动输入，或到“持仓再平衡”上传现有 `.xlsx` 总账。

### 以后每次启动

```powershell
Set-Location C:\ETF\eft-market-monitor
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1
```

### 端口被占用

改用其他端口：

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8502
```

然后访问 http://127.0.0.1:8502 。

## 6. 使用 Excel 持仓再平衡

1. 在侧栏打开“持仓再平衡”。
2. 上传现有“基金持仓总账” `.xlsx` 文件。
3. 确认目标比例，默认偏离阈值5个百分点、本轮比例25%。
4. 分别查看最终目标差额、理论本轮计划和已确认资金支持的模拟。
5. 核实持有期、赎回限制、到账时间、费用及跨账户调拨条件。
6. 实际人工操作后更新原Excel，再上传重新分析。

没有赎回信息时标记“需人工确认”，未确认的卖出不为保守买入融资。文件仅会话内分析；原Excel请自己保管，**不要放入Git仓库或提交到GitHub**。下载的分析CSV也包含个人信息，应自行保管。

详细字段与金额规则见 `docs\REBALANCE.md`。

## 7. 生成策略研究报告

先更新历史行情，再执行：

```powershell
.\.venv\Scripts\python.exe -m jobs.strategy_report
```

生成：

- `STRATEGY_REPORT.md`：策略结论和比较表。
- `reports\strategies\nav_drawdown.html`：双击后用浏览器打开净值/回撤交互图。
- 同目录CSV：完整指标、分段表现、逐次决策及原因。

参数位于 `config\strategies.json`。历史因子缺失的A/C策略会标注不可计算，不生成虚构收益。回测为研究结果，不保证未来收益或回撤。

## 8. 配置自动更新

电脑需在触发时开机并联网；程序不会自行成为后台调度服务。

打开 Windows“任务计划程序”，建立两个任务：

| 任务 | 建议时间（中国时区电脑） | 运行文件 |
|---|---|---|
| 收盘数据更新 | 周一至周五15:35 | `C:\ETF\eft-market-monitor\jobs\run_close.cmd` |
| 份额补齐 | 周一至周五08:50 | `C:\ETF\eft-market-monitor\jobs\run_shares.cmd` |

在“操作→启动程序”中选择对应 `.cmd`，起始目录设为 `C:\ETF\eft-market-monitor`。勾选错过计划后尽快运行；失败30分钟后重试、最多2次；避免同一任务并行运行。

内置时间判断采用上海时区。若电脑设置其他时区，触发时间需自行换算。节假日可能无新数据，不会补造行情。Windows任务脚本尚未做Windows实机验收，设置后应右键“运行”并检查日志与数据日期。

更详细说明见 `docs\SCHEDULING.md`。

## 9. 更新程序

先按 `Ctrl+C` 停止网页程序，在项目目录执行：

```powershell
git status
git pull --ff-only
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1
```

如果 Git 提示存在本地修改或分支分歧，不要使用强制重置；先保留自己的配置与修改再处理。数据库、日志和私人Excel不会因正常 `git pull` 被同步到远程。

## 10. 备份与恢复

先停止网页和更新任务，再备份：

- `data\market.sqlite3` 以及存在时同目录的 `market.sqlite3-wal`、`market.sqlite3-shm` 文件。
- 自己填写的配置与持仓Excel。
- 需要保留的本地分析结果。

将备份保存在私人位置。数据库包含“我的组合”和历史快照，不要上传Git。恢复时停止所有相关程序，保留原文件，整体恢复同一时刻备份，不能混用不同时间的数据库与WAL文件。

如果数据库损坏，应用不会自动删除重建。先备份损坏文件，再从已知完好备份恢复；行情可以重新下载，但个人组合与历史记录未必可重建。

## 11. 常见问题

| 问题 | 处理方式 |
|---|---|
| `py` 或 `git` 找不到 | 确认软件已安装，重新打开PowerShell；Python需安装3.11 |
| `No module named ...` | 使用 `.venv\Scripts\python.exe`，重新执行依赖安装 |
| `app.py` 找不到 | 先进入 `C:\ETF\eft-market-monitor` |
| 页面无行情 | 执行首次更新命令，检查来源失败提示和日志 |
| 数据是昨天的 | 15:30前使用上一已收盘交易日；收盘后需更新，刷新页面本身不联网更新 |
| Excel无法分析 | 检查“当前持仓/目标组合”、目标总和100%、数字合法、目标可编辑列；不支持旧 `.xls` |
| 本轮已确认金额为0 | 可能赎回条件未知、无法筹资、偏离未超阈值或目标桶尚未指定基金；查看原因 |
| 策略A/C没有收益结果 | 历史时点因子尚不足，不是安装失败 |
| 更新接口报错 | 保留缓存，稍后重试；检查 `logs\market.log`，不必删除数据库 |

## 12. Linux/macOS简要步骤

安装 Python3.11与Git后，在终端执行：

```bash
git clone https://github.com/fow1840/eft-market-monitor.git
cd eft-market-monitor
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m jobs.update close --force
.venv/bin/python -m jobs.update shares --force
.venv/bin/python -m streamlit run app.py --server.address 127.0.0.1
```

访问 http://127.0.0.1:8501 。自动任务可使用cron，参考调度文档。本项目主要代码在Python3.11 Linux环境通过测试；本指南不等于Windows/macOS实机验收记录。
