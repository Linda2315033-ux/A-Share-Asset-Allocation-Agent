# A股智能资产配置研究 Agent
### A-Share Asset Allocation Research Agent

基于 **Python、AKShare、规则驱动资产配置、历史回测、智谱 GLM 和 Streamlit** 构建的A股智能资产配置研究系统。

项目尝试将股票行情维护、市场状态识别、策略选择、组合权重计算、研究结果校验和大语言模型解释整合为可追溯的自动化研究流程。

**项目定位：金融研究与工程实践，不连接实盘交易系统，不提供投资建议。**

## 1. 项目概览

本项目以沪深主板股票为研究对象，构建从历史数据到组合研究结果的自动化流程：

```text
A股历史行情 / AKShare
        |
        v
数据增量更新与完整性校验
        |
        v
沪深300市场状态识别
        |
        v
策略选择与股票筛选
        |
        v
股票 / 现金目标权重计算
        |
        v
研究结果与风险约束校验
        |
        +----> GitHub私有仓库：历史数据备份
        |
        +----> GitHub公开仓库：精简研究预览
        |
        +----> Streamlit：研究结果展示
        |
        +----> 智谱GLM：只读工具调用与自然语言解释
```

系统采用**规则计算与大语言模型解释分离**的设计。

股票筛选、策略选择和目标权重由Python研究模块计算。GLM通过只读工具获取已保存的研究结果，并解释市场状态、配置依据和主要风险，不直接决定交易指令或执行下单。

## 2. 核心功能与当前进度

| 模块 | 功能 | 当前状态 |
|---|---|---|
| A股历史数据库 | 维护约3,189只沪深主板股票的原始及前复权历史行情 | 已建立 |
| 智能增量更新 | 检查股票行情日期，识别需要更新的股票并进行下载与校验 | 已实现，部分真实调用通过 |
| 市场状态识别 | 基于沪深300指数趋势和波动率识别市场环境 | 已实现 |
| 动态资产配置 | 根据市场状态选择策略并计算股票与现金权重 | 已实现 |
| 历史回测 | 分析策略历史净值、回撤及绩效指标 | 已实现，依赖相应回测输出 |
| GLM研究解释 | 通过只读工具获取研究结果，解释策略、权重及风险 | 本地测试通过 |
| Streamlit网页 | 展示市场状态、组合研究及GLM交互 | 已部署，云端研究数据读取待完善 |
| 私有行情备份 | 通过GitHub私有仓库Release保存历史数据 | 初始备份与云端恢复已验证 |
| 每日自动更新 | GitHub Actions按计划恢复数据、更新行情并执行研究流程 | **定时任务已启用，首次全链路运行待验证** |
| 公开研究预览 | 将经过校验的精简研究结果提交到公开仓库 | 工作流已配置，自动发布待验证 |

项目目前处于**自动化运行试验阶段（Scheduled Pilot）**，而非已经完成生产级验收的交易系统。

## 3. 资产配置研究逻辑

### 3.1 市场状态识别

系统结合沪深300指数的趋势、收益和波动率等指标，对市场环境进行分类，并据此调整股票与现金的配置比例。

### 3.2 策略选择

当前研究框架包含以下策略：

| 策略 | 适用研究场景 | 目标股票仓位 |
|---|---|---:|
| `MOMENTUM` | 上涨趋势 | 80% |
| `DEFENSIVE` | 下跌趋势 | 30% |
| `LOW_VOLATILITY` | 震荡环境 | 60% |
| `RISK_REDUCTION` | 高波动风险环境 | 40% |

上述比例是研究模型的预设配置规则，不代表实时投资建议。

系统根据市场状态选择相应策略，再执行股票筛选、权重计算和风险检查。

### 3.3 历史研究示例

在2026年10月14日生成的本地研究预览中，模型识别出下跌趋势，选择`DEFENSIVE`策略，形成股票仓位30%、现金仓位70%的研究组合。

该结果仅代表对应日期的历史研究快照，不是当前实时信号，也不意味着组合已实际交易。

## 4. GitHub Actions每日自动更新

本项目已配置并启用GitHub Actions定时工作流：

`.github/workflows/daily-research-v2.yml`

工作流名称：

`A-share daily research V2 (scheduled pilot)`

### 自动运行时间

```yaml
on:
  workflow_dispatch:
  schedule:
    - cron: '30 9 * * 1-5'
```

计划在**每周一至周五北京时间17:30**触发。

GitHub Actions采用UTC时间配置，UTC 09:30对应北京时间17:30。实际任务启动可能存在平台调度延迟；周一至周五不一定都是A股交易日。

### 自动化执行流程

```text
GitHub Actions定时触发
          |
          v
检出公开源代码
          |
          v
安装Python依赖
          |
          v
恢复最新完整私有行情备份
          |
          v
执行每日行情更新和研究流程
          |
          v
校验新生成的研究结果
          |
          v
创建新的私有历史数据备份
          |
          v
生成精简公开研究JSON
          |
          v
提交至公开仓库
```

工作流主要使用以下脚本：

| 文件 | 作用 |
|---|---|
| `stock_agent_github_restore_latest_v2.py` | 恢复最新完整私有数据 |
| `stock_agent_daily_automation_v3.py` | 执行每日数据更新与研究自动化 |
| `stock_agent_verify_daily_v2.py` | 校验新生成的研究结果 |
| `stock_agent_github_backup_v1.py` | 创建私有数据备份 |
| `stock_agent_publish_preview_v1.py` | 生成精简公开研究结果 |

### 当前验证状态

截至2026年10月15日：

- 定时触发配置已提交并启用。
- GitHub Actions私有数据恢复流程已测试成功。
- 每日行情更新及研究流程已配置。
- 私有数据写入和公开研究结果提交步骤已配置。
- **完整云端每日更新、生成新备份及公开发布流程尚未完成首次成功运行验证。**

因此，当前状态为**已启用自动调度，等待实际运行验收**，不应理解为所有股票数据已经每天成功更新。

### 安全保护

每日写入模式保留北京时间16:00的时间限制，防止过早启动写入流程。

工作流按步骤执行；校验或更新步骤失败时，后续普通步骤默认不会继续运行。

私有备份步骤安排在公开研究结果发布之前，以减少数据更新成功但尚未备份的风险。

研究结果未通过校验时，不应作为正式研究信号发布。

## 5. 数据存储与隐私设计

项目采用**公开源代码与私有历史数据分离**的方式。

### 公开仓库

[A-Share-Asset-Allocation-Agent](https://github.com/Linda2315033-ux/A-Share-Asset-Allocation-Agent)

主要存放：

- Python研究与自动化源代码
- GitHub Actions工作流
- Streamlit网页代码
- 依赖说明及项目文档
- 允许公开的精简研究结果

### 私有数据仓库

完整股票历史行情保存在独立的GitHub私有仓库中，通过Release归档和恢复。

主要包括：

- 股票原始历史行情（raw）
- 股票前复权历史行情（qfq）
- 股票池与辅助元数据
- 市场指数相关数据

完整历史行情不随公开源代码仓库分发。

GitHub Actions通过仓库Secrets访问私有数据，使用：

- `PRIVATE_DATA_READ_TOKEN`
- `PRIVATE_DATA_WRITE_TOKEN`

API Key及访问Token不得写入代码、README、公开JSON或提交记录。

## 6. Streamlit可视化网页

项目使用Streamlit构建中文研究界面，展示市场状态、策略选择、股票权重、现金比例、研究风险以及可用的历史回测信息。

当前云端部署入口文件为：

`stock_agent_dashboard_v4.py`

本地启动：

```powershell
python -m streamlit run stock_agent_dashboard_v4.py
```

网页通过`stock_agent_glm_daily_v2.py`中的只读研究工具获取研究数据。

**当前部署状态：** Streamlit云端应用已能够启动，但由于云端尚未读取到符合校验要求的最新研究预览，完整研究结果展示仍待打通。

网页能够启动不等于行情更新已经完成，也不等于研究结果已经自动发布。

## 7. 智谱GLM研究Agent

GLM用于理解研究问题，并通过工具调用解释已有的研究数据。

典型问题包括：

- 当前研究快照反映了什么市场状态？
- 为什么选择当前资产配置策略？
- 股票仓位与现金比例如何确定？
- 组合包含哪些股票，目标权重是多少？
- 当前研究结果有哪些风险和数据限制？

系统强调：

1. 涉及市场与组合事实时，优先使用经过校验的研究工具数据。
2. 不允许模型自行编造股票权重、行情或回测绩效。
3. 不允许模型绕过Python策略规则修改组合。
4. 不提供实盘下单能力。
5. 不将历史研究快照描述为实时市场信号。

本地运行前，需要自行配置智谱API Key，例如在PowerShell当前会话中：

```powershell
$env:ZHIPU_API_KEY = "YOUR_API_KEY"
```

请勿将真实密钥提交至GitHub。

## 8. 本地环境与运行

### 环境要求

- Python 3.11或更新版本（GitHub Actions使用Python 3.12）
- Windows PowerShell、VS Code或其他兼容开发环境
- 可用的Python依赖安装网络
- 更新行情时需要访问相应数据源
- 使用在线GLM功能时需要有效API Key

### 安装依赖

```powershell
python -m pip install -r requirements.txt
```

### 数据检查模式

```powershell
python stock_agent_daily_automation_v3.py
```

默认检查模式用于核查本地数据及研究流程，不等于执行每日行情写入。

### 手动执行每日更新

```powershell
python stock_agent_daily_automation_v3.py --daily-update --confirm-daily-update
```

该命令可能修改本地行情数据。执行前应确认已有完整备份，并满足程序规定的时间与数据校验条件。

### 生成研究预览

```powershell
python stock_agent_daily_preview_v1.py
```

此命令依赖已准备好的本地数据，不会自动创建完整历史行情数据库。

### 检查GLM研究预览

```powershell
python stock_agent_glm_daily_v2.py --self-test
python stock_agent_glm_daily_v2.py --check
```

在线研究问答：

```powershell
python stock_agent_glm_daily_v2.py --ask "请解释最新研究预览中的市场状态、策略权重与主要风险。"
```

**注意：** 公开仓库不包含完整历史行情。首次本地复现需要自行准备合法来源的数据及相应目录结构，仅安装依赖不能直接重现所有历史研究结果。

## 9. 主要项目文件

| 文件 | 功能 |
|---|---|
| `stock_agent_dashboard_v4.py` | Streamlit研究网页 |
| `stock_agent_glm_daily_v2.py` | GLM只读研究工具与问答 |
| `stock_agent_daily_automation_v3.py` | 每日研究自动化入口 |
| `stock_agent_daily_pipeline_v2.py` | 数据与研究流程预检 |
| `stock_agent_daily_preview_v1.py` | 生成研究快照 |
| `stock_agent_verify_daily_v2.py` | 每日研究结果校验 |
| `stock_agent_github_restore_latest_v2.py` | 私有行情恢复 |
| `stock_agent_github_backup_v1.py` | 私有行情备份 |
| `stock_agent_publish_preview_v1.py` | 公开研究预览生成 |
| `stock_mainboard_smart_update_v1.py` | 智能增量更新计划 |
| `stock_mainboard_incremental_update_v55.py` | 行情增量下载与写入 |
| `stock_market_state.py` | 市场状态识别 |
| `stock_agent_current_decision_v54.py` | 组合研究决策逻辑 |
| `.github/workflows/daily-research-v2.yml` | 定时自动更新工作流 |

## 10. 研究限制与风险说明

**数据时点与ST识别：** 当前ST股票识别依赖名称信息，相关快照的交易日期尚未完成独立核验。`st_quote_date_verified=false`时，正式发布应受到限制。

**历史数据偏差：** 股票池可能存在幸存者偏差；历史ST状态、复权修订、退市、停复牌和公司行为等信息尚未完成全面时点核验。

**回测限制：** 历史结果依赖数据范围、交易成本、调仓规则、流动性及其他模型假设。历史绩效不能保证未来收益。

**数据更新限制：** 行情源可能存在延迟、缺失或修订。程序被定时触发并不意味着所有股票都已更新到目标交易日。

**自动化运行限制：** 当前GitHub Actions已启用定时任务，但首次完整云端运行尚未验收。后续需要检查数据更新、私有备份、研究校验与公开结果发布是否全部成功。

**研究用途限制：** 项目不连接券商交易接口，不执行证券交易，所有输出均为研究性信息。

## 11. 后续开发计划

- 验证首次GitHub Actions定时运行的完整结果
- 检查私有行情备份能否持续生成和恢复最新版本
- 完善Streamlit云端研究预览的数据读取
- 加强数据完整性、ST时点和复权修订核验
- 增加自动运行失败通知和异常监控
- 改进历史回测的可复现性和风险评估

## 12. 免责声明

本项目仅用于学术研究、金融数据分析和智能体工程实践。

项目生成的市场状态、股票筛选、组合权重、回测结果及大语言模型解释均不构成投资建议，也不代表实时行情、实际交易指令或未来收益保证。
