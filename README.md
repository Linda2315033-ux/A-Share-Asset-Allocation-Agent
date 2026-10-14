# A股智能资产配置研究 Agent

> 基于 Python、AKShare、规则驱动资产配置、历史回测与智谱 GLM 工具调用的 **研究型** A 股主板股票 Agent。**不提供实盘交易、不构成投资建议。**

## 1. 项目概览

项目面向沪深主板股票研究，尝试把 **数据更新 → 数据完整性检查 → 市场状态识别 → 股票筛选与仓位配置 → 研究预览 → GLM 解读 → Streamlit 可视化** 串成可追溯流程。模型负责调用只读工具并解释研究结果；组合规则和权重由 Python 计算，GLM 不直接下单或擅自修改仓位。

### 已实现功能及验证范围

| 模块 | 功能 | 当前验证情况 |
|---|---|---|
| 股票数据 | 维护约 3,189 只沪深主板股票的 raw / 前复权(qfq) 历史数据 | 已建立本地数据集；不随仓库公开提供 |
| 智能增量更新 | 对已达到目标交易日的股票跳过重复下载，落后股票交给 V5.5 核验 | 5 只股票真实调用成功；1 只股票隔离环境 `UPDATED`/备份成功 |
| 市场识别 | 使用沪深300指数收益与波动率识别趋势和波动状态 | 已实现并用于研究预览 |
| 组合决策 | 根据市场状态选择策略，筛选股票，确定股票/现金权重 | V5.4 研究预览已成功生成 |
| 历史回测 | 展示动态 Agent 组合与沪深300基准、净值/回撤/绩效指标 | 依赖已有回测输出文件；不把今日股票回填到历史 |
| 每日自动化 | V3检查模式、日志、失败停止、运行锁等 | 检查模式成功；真实全链路无人值守尚未验收 |
| GLM 工具调用 | 读取通过校验的最新研究快照并解释市场、策略、权重和风险 | 本地 `--self-test`、`--check` 与在线 `--ask` 已通过 |
| Streamlit 网页 | 市场、组合、中文规则/风险、历史回测、GLM 问答 | 网页代码已开发；部署环境需自行验证 |

## 2. 工作原理

```text
AKShare / 本地 raw + qfq CSV
          │
          ▼
股票增量更新 + 沪深300指数刷新 + ST名称快照
          │
          ▼
交易日 / raw-qfq / 股票池 / ST日期核验检查
          │
          ▼
市场状态识别 → 策略选择 → 股票筛选 → 目标权重
          │
          ▼
只读研究预览（非正式发布，非交易指令）
          ├── 历史回测结果 → Streamlit 图表
          └── GLM 只读工具调用 → 中文自然语言解释
```

示例：在 **2026-10-14** 的本地研究快照中，市场状态为下跌趋势，Agent 选择 `DEFENSIVE` 策略，筛选出 4 只股票，目标股票仓位 **30%**、现金 **70%**。这是特定历史快照的研究结果，不代表当前实时信号。

## 3. 环境与安装

- Windows + PowerShell / VS Code（也可自行适配其他系统）
- Python **3.11 或更新版本**（代码使用 `tomllib`、`zoneinfo`；具体第三方包兼容性以安装环境为准）
- 需要联网更新数据时，能够访问 AKShare 使用的相关数据源
- 使用 GLM 在线问答时，需要自行申请智谱 API Key

```powershell
# 在项目根目录运行
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

如 PowerShell 阻止激活虚拟环境，也可以直接执行 `.venv\Scripts\python.exe -m pip install -r requirements.txt`。

**数据准备：** 本项目不附带完整股票历史数据。首次使用需自行合法获取并校验数据，放在 `data/stocks/mainboard_history_v1/raw/`、`data/stocks/mainboard_history_v1/qfq/`，并准备 `data/stocks/universe.csv`、`data/stocks/market/sh000300.csv`。仅安装依赖并不能直接复现已保存的 2026 年研究结果。相关数据的许可、准确性与历史时点可得性需自行核查。

## 4. 如何使用

所有命令都在仓库根目录运行。

### A. 检查每日数据完整性（不修改行情）

```powershell
python stock_agent_daily_automation_v3.py
```

成功识别数据检查通过但正式发布被阻断时，可能返回 `CHECK_OK_PUBLICATION_BLOCKED`，退出码为 0。ST名称快照日期未经独立核验，因此 **`formal_publication_allowed=false` 是预期的安全限制**。

### B. 预览需要联网核查的股票（不修改行情）

```powershell
python stock_mainboard_smart_update_v1.py
```

默认只生成更新计划；交易日已达标的股票跳过下载。停牌股票可能没有目标交易日K线，不应人为补齐。

### C. 更新行情（会写入数据，谨慎使用）

```powershell
# 仅在充分备份、确认数据源和网络正常后，人工执行
python stock_agent_daily_automation_v3.py --daily-update --confirm-daily-update
```

该模式会修改本地行情缓存并尝试刷新指数和ST快照；运行前建议备份 `data/`。它并非已经完成全量无人值守验收的生产任务。执行后查看 `output/stock_agent_daily_automation_v3/` 的运行日志。北京时间16:00以后运行也不能保证行情源已完整更新，必须以数据检查结果为准。

### D. 生成每日研究预览

```powershell
python stock_agent_daily_preview_v1.py
```

研究快照位于 `output/stock_agent_daily_preview/<交易日>/<运行编号>/`。该脚本依赖已经准备好的本地行情、股票池与其他研究模块；**不会自动下载行情**。

### E. GLM 只读问答

```powershell
python stock_agent_glm_daily_v1.py --self-test
python stock_agent_glm_daily_v1.py --check
python stock_agent_glm_daily_v1.py --ask "请解释最新研究预览中的策略、股票权重和主要风险。"
```

在线调用前，在当前 PowerShell 会话中设置环境变量（不要把密钥写入代码或提交到 Git）：

```powershell
$env:ZHIPU_API_KEY = "请在此输入你自己的密钥"
```

也可以使用本地 `.streamlit/secrets.toml`，但**该文件已列入 `.gitignore`，绝不可提交**。GLM 调用依赖 `stock_agent_llm_v2.py` 中的模型配置，默认模型名称由代码及 `ZHIPU_MODEL` 环境变量决定。

### F. 启动网页

```powershell
python -m streamlit run stock_agent_dashboard_v3.py
```

在终端显示的本地地址打开网页。网页读取最近一次**通过校验的研究预览**；没有有效预览时会提示先生成。历史回测模块还需要 `historical_decisions.csv` 与 `backtest_v31_nav.csv`（可放项目根目录或 `output/` 子目录）；没有文件时不会编造绩效。图表中的“当前策略历史条件表现”与“始终采用当前策略的独立回测”不是同一概念。

## 5. 主要文件

| 文件 | 用途 |
|---|---|
| `stock_agent_dashboard_v3.py` | Streamlit 中文研究网页 |
| `stock_agent_glm_daily_v1.py` | GLM 调用已验证研究快照的只读工具 |
| `stock_agent_llm_v2.py` / `stock_agent_tools.py` | 现有 GLM 配置与研究工具 |
| `stock_agent_current_decision_v54.py` | 最新组合研究预览的决策逻辑 |
| `stock_backtest_signals.py` / `stock_backtest_policy.py` | 因子、市场状态与策略规则 |
| `stock_agent_daily_preview_v1.py` | 生成独立的每日研究快照 |
| `stock_agent_daily_pipeline_v2.py` | 数据完整性与正式发布限制检查 |
| `stock_agent_daily_automation_v3.py` | 每日自动化流程入口 |
| `stock_mainboard_smart_update_v1.py` | 智能选择待核查股票 |
| `stock_mainboard_incremental_update_v55.py` | 历史行情下载、校验、备份、写入 |
| `stock_market_state.py` | 沪深300市场状态识别 |
| `stock_universe_daily_update_v1.py` | 股票名称与ST标记快照更新 |

## 6. 风险、限制与复现说明

1. **研究用途**：不连接券商交易接口，不自动下单，不构成投资建议。
2. **ST日期未经核验**：当前按名称识别ST，无法独立证明快照对应交易日；正式发布被阻断。
3. **历史偏差**：当前股票池可能存在幸存者偏差；历史ST状态、复权修订、公司行为、停复牌及退市事件尚未完成独立时点核验。
4. **回测假设**：历史收益取决于样本、交易成本、调仓、流动性、现金收益及成交可执行性假设；不能作为未来收益保证。
5. **行情更新**：对已达到目标交易日的股票跳过下载可能遗漏历史复权修订；建议定期做完整数据核查。
6. **可复现性**：仓库不包含全部行情与本地运行输出；需要自行准备数据。示例回测数据如经许可公开，需说明来源、日期与生成方法。
7. **验证边界**：V3默认检查模式、模拟流程测试及GLM在线工具调用已验证；全量自动更新、Windows任务计划程序及生产级故障恢复尚未完成验收。

## 7. 后续计划

- 完成真实全链路每日更新与故障注入验收
- 增加Windows任务计划程序、超时监控和异常通知
- 改进历史时点数据、交易成本与停复牌处理
- 统一项目结构，增加可复现的小样本数据与自动化测试

## 8. 免责声明

本仓库为学术与工程学习项目。所有市场判断、股票筛选、目标权重及历史回测仅供研究与教学展示，不代表实时行情、正式投资建议或实际交易信号。
