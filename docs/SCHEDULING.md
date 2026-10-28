# 本地更新任务

在项目目录、Python 3.11 虚拟环境执行：

```bash
python -m jobs.update close
python -m jobs.update shares
```

close 在上海时间工作日15:30之后运行，更新七只ETF、四个指数估值、全A宽度，并保存市场/组合/建议快照。
shares 在上海时间工作日08:45之后运行，尝试补充昨日官方份额并累计观察值。
周末不执行；节假日接口可能无记录，不伪造更新。服务不持续运行，须由操作系统计划任务启动。
`--force` 仅用于手工重试，绕过时间门槛；行情服务仍排除未完成日线。
数据服务最多两次重试，有限超时，失败记录日志并保留旧缓存；任一来源失败不会阻塞其他模块。
退出码1表示至少一个来源失败，0表示执行成功或未到时间跳过；缺失字段仍在数据结果中明确标记。

## Windows 任务计划程序

1. 在任务计划程序创建两个任务，仅使用当前用户本地权限。
2. 收盘任务设置工作日15:35，运行仓库绝对路径下 `jobs\run_close.cmd`。
3. 份额任务设置工作日08:50，运行 `jobs\run_shares.cmd`。
4. 开启“错过计划后尽快运行”，失败30分钟后重试，最多2次；禁止同任务并行。
5. Python 需已按 README 安装到仓库 `.venv`，日志在 `logs/market.log`。

计划按上海时区设计；操作系统触发时间需按本地时区换算。没有在本次 Linux 云环境创建或运行 Windows 任务计划程序，脚本仅静态检查。

## Linux cron 示例

系统为上海时区时：

```cron
35 15 * * 1-5 cd /absolute/project && .venv/bin/python -m jobs.update close
50 8 * * 1-5 cd /absolute/project && .venv/bin/python -m jobs.update shares
```

不使用第三方AI，不调用证券交易接口。
