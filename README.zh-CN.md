# QuantAdvisorResearch

[English](README.md) | [简体中文](README.zh-CN.md)

QuantStrategyLab 的“智慧投顾研究系统”协调仓库。它把事件证据、主题动量、市场确认和 AI shadow 背景整理成普通投资者能读懂的研究结论；不下单、不管理仓位、不接券商凭证，也不做账户级个性化建议。

线上站点：<https://quantstrategylab.github.io/QuantAdvisorResearch/>

主要文档：

- [系统设计](docs/system_design.zh-CN.md) / [System design](docs/system_design.md)
- [数据源与因子路线](docs/data_factor_roadmap.zh-CN.md) / [Data and factor roadmap](docs/data_factor_roadmap.md)
- [通知格式](docs/notification_format.zh-CN.md) / [Notification format](docs/notification_format.md)
- [Artifact contract](docs/advisory_contract.md)

当前运行节奏是：**周度公开智慧投顾研究 + 周度事件/主题刷新 + 月度 AI shadow 背景 + 单独月度复盘 artifact**。月度复盘只做变化回顾和月末检查；只要报告里仍保留短线 `1-10个交易日` 和中线 `2-12周` 窗口，公开推荐就不应改成月更。

## 仓库定位

这个仓库把事件研究、主题动量、市场确认和 AI shadow 产物组合成智慧投顾研究 artifact：

- `PoliticalEventTrackingResearch`：政治/公开事件事实、催化剂、来源置信度。
- `ResearchSignalContextPipelines`：已保存的长周期 AI shadow context。
- 其他量化策略/快照仓库：保持独立，不作为当前推荐链路的直接输入。
- 各券商平台仓库：继续只负责执行链路；本仓库不调用它们。


## 短中长线来源分工

智慧投顾研究系统由本仓库做最终合成，三个周期的输入分工如下：

- 短线（1-10 个交易日）：事件/新闻政策催化 + 自动生成的 `market_confirmation.csv`，重点看相对强度、成交量、回撤和波动。
- 中线（2-12 周）：`ResearchSignalContextPipelines` 的 `theme_momentum_snapshot.json`，现在明确标记为 `medium_horizon_theme_context`，重点看主题动量和个股动量。
- 长线（1-3 年）：`ResearchSignalContextPipelines` 的 `latest_signal.json` / `signal_history/*.json`，作为 AI shadow 背景。

最终研究结论仍由本仓库确定性合成。信号上下文仓库不直接输出短线推荐，也不替代本仓库的最终决策。本仓库会为最终推荐记录短/中/长线独立评分和独立门槛，并在 JSON 里记录长线背景是否可用。公开页面按每个周期自己的门槛渲染完整卡片，所以同一只股票在中线和长线都成立时，可以同时出现在两个周期栏里。

## 当前 MVP

当前实现一个确定性的智慧投顾研究报告生成器：

```bash
python scripts/build_advisory_report.py \
  --as-of 2026-05-30 \
  --cadence weekly \
  --political-events examples/political_events.example.csv \
  --political-watchlist examples/political_watchlist.example.csv \
  --ai-signal examples/research_signal_context.example.json \
  --output-json data/output/advisory_report.example.json \
  --output-md data/output/advisory_report.example.md
```

命令会同时写出 `data/output/advisory_report.example.json.manifest.json`。

输出包括：

- 推荐标的
- 推荐等级：重点推荐、观察、先核验来源、暂缓、背景跟踪
- 推荐层级：一级推荐、二级推荐、观察名单、来源核验
- 适合周期：短线、中线、长线，并明确时间窗口
- 周期窗口：短线=1-10个交易日，中线=2-12周，长线=1-3年
- 周期说明：短线风险、事件驱动验证周期、长期观察理由
- 来源可信度：高、中、低、混合、无事件
- 中长线、价值、事件、宏观等策略风格标签
- 证据分数和风险分数
- 推荐理由、风险、复核清单
- 日/周/月复盘 cadence

## 版本管理

- Python 包版本：`0.1.3`
- 报告 schema：`schema_version = 5`
- 报告 contract：`model_recommendations.v5`
- 报告 manifest：`<output-json>.manifest.json`

manifest 会记录 JSON/Markdown 的 SHA256、`as_of`、cadence、来源 artifact、政策边界、Git SHA、GitHub run id 和 contract version。这样和快照/AI artifact 仓库保持同类版本纪律，但不会把推荐输出变成可执行策略 target。

## 来源模式

如果报告输入来自 `examples/`，JSON 里仍会标记 `source_mode=fixture`，但公开 HTML/RSS/Telegram 不再显示 fixture 或来源模式标签。周度/月度和 Pages 发布 workflow 默认读取 `PoliticalEventTrackingResearch` 的 `data/live/*`，因此正式发布的审计 artifact 应为 `source_mode=operator_supplied`。

`source_mode` 继续保留在 JSON 契约里用于审计，不作为公开页面文案。

## 边界

本仓库负责：

- 智慧投顾研究 artifact schema
- 确定性评分和复核规则
- 日/周/月报告生成
- 历史智慧投顾研究记录和后续复盘入口

本仓库不负责：

- 券商 API、下单、调仓
- 目标仓位、目标股数、账户级资产配置
- 投资者适当性判断
- 模型 provider 路由或 prompt 执行
- 付费行情原始数据再分发

## AI 使用边界

本仓库不直接调用 Codex、OpenAI、Anthropic 或其他模型 API。它只读取 `ResearchSignalContextPipelines` 已保存的 `mode=shadow` artifact。

这三个仓库里，只有 `ResearchSignalContextPipelines` 的月度 shadow signal 流程会涉及 AI，而且模型执行也委托给 `QuantStrategyLab/CodexAuditBridge`。模型 API key 和 fallback provider routing 都应集中在那里，不应放到本仓库。

## 合规提醒

“不下单、不管仓位”会降低执行风险，但不自动消除投顾/推荐监管风险。只要面向投资者提供具体证券推荐，在不同商业模式下仍可能触发投资顾问、经纪推荐、适当性或 Reg BI 义务。

因此当前默认：

- `non_personalized_recommendations_allowed=true`
- `execution_allowed=false`
- `portfolio_allocation_allowed=false`
- `personalized_advice_allowed=false`
- `account_specific_advice_allowed=false`
- `audience_scope=non_personalized_model_research`

## 测试

```bash
python -m pytest -q
```

## 周度复盘

`.github/workflows/weekly_advisory_review.yml` 会 checkout 本仓库、`PoliticalEventTrackingResearch`
和 `ResearchSignalContextPipelines`，生成周度 `model_recommendations` 智慧投顾研究报告并上传为 GitHub Actions artifact。

它不会提交文件、不会通知投资者、不会创建订单。

`.github/workflows/publish_advisory_site.yml` 会每周发布 HTML/JSON/RSS 站点。如果仓库 secrets 配置了 `TELEGRAM_BOT_TOKEN` 和 `TELEGRAM_CHAT_ID`，Pages 部署成功后会发送一条智慧投顾研究 Telegram 摘要；如果没配置，通知步骤会跳过；Telegram 发送异常会记录在日志里，但不阻断网页/RSS 发布。

周度发布是有意保留的：短线结论如果只月更会过期；月度 AI shadow 只提供长周期背景，不作为每周追热点的模型输入。

## 月度复盘

`.github/workflows/monthly_advisory_review.yml` 每月生成一次 `monthly_advisory_review` artifact，用来检查本月最终推荐、短/中/长线分布，以及相对上一份报告的新增、移除和保留标的。

本地生成：

```bash
python scripts/build_monthly_review.py \
  --current-report data/output/weekly_advisory_review/advisory_report_2026-05-30.json \
  --output-json data/output/monthly_advisory_review/monthly_review_2026-05-30.json \
  --output-md data/output/monthly_advisory_review/monthly_review_2026-05-30.md
```

如果传入 `--previous-report`，会输出新增、移除和保留标的；不传时仍能生成本月快照，但会记录数据质量提示。这个 workflow 只上传 artifact，不发布网页，也不替代周度公开推荐。

## RSS / 静态页面

生成 HTML + RSS 预览：

```bash
python scripts/publish_advisory_site.py \
  --reports data/output/weekly_advisory_review/advisory_report_2026-05-30.json \
  --output-dir site \
  --site-url https://quantstrategylab.github.io/QuantAdvisorResearch
```

本地打开 `site/index.html`，RSS 文件是 `site/feed.xml`。
`.github/workflows/publish_advisory_site.yml` 会部署到 GitHub Pages：
<https://quantstrategylab.github.io/QuantAdvisorResearch/>

当前公开页面、RSS 标题和 Telegram 摘要默认使用简体中文（`zh-CN`），并统一使用“智慧投顾研究系统”的对外表述。
JSON 字段名继续保持英文契约键，避免破坏下游程序读取。

发布 workflow 默认已经读取 `PoliticalEventTrackingResearch` 内的真实 CSV。手工触发通常只需要传日期；只有刻意测试其他 artifact 时才覆盖路径：

```bash
gh workflow run "Publish Intelligent Advisory Site" \
  --repo QuantStrategyLab/QuantAdvisorResearch \
  -f as_of=2026-05-30
```

通知格式设计见 [docs/notification_format.zh-CN.md](docs/notification_format.zh-CN.md)。
数据源和因子完善路线见 [docs/data_factor_roadmap.zh-CN.md](docs/data_factor_roadmap.zh-CN.md)。

## 主题动量展示

`build_advisory_report.py` 支持可选的主题动量快照输入：

```bash
python scripts/build_advisory_report.py \
  --as-of 2026-05-30 \
  --cadence weekly \
  --political-events examples/political_events.example.csv \
  --political-watchlist examples/political_watchlist.example.csv \
  --ai-signal examples/research_signal_context.example.json \
  --theme-momentum examples/theme_momentum_snapshot.example.json \
  --market-confirmation examples/market_confirmation.example.csv \
  --output-json data/output/advisory_report.example.json \
  --output-md data/output/advisory_report.example.md
```

主题动量会生成 `theme_first_candidates[]`，作为 JSON/Markdown 中的解释和审计材料。公开页面、RSS 和 Telegram 摘要默认只显示最终推荐，避免把候选池误读为买入清单。

基础 `recommendations[]` 评级仍来自事件、watchlist 和 AI 背景；`final_decisions` 会用中线主题动量和可选市场确认对最终公开列表排序。候选池不改变仓位或执行状态。
线上 workflow 如果找不到 `data/output/theme_momentum_snapshot.json`，会自动跳过这个展示区块。

## 市场确认

`scripts/build_market_confirmation.py` 会从 watchlist、信号上下文和主题动量快照收集股票代码，生成 `market_confirmation.csv`：

```bash
python scripts/build_market_confirmation.py \
  --as-of 2026-05-30 \
  --political-watchlist examples/political_watchlist.example.csv \
  --ai-signal examples/research_signal_context.example.json \
  --theme-momentum examples/theme_momentum_snapshot.example.json \
  --output data/output/market_confirmation_2026-05-30.csv
```

字段包括 `return_5d`、`return_20d`、`return_63d`、相对 SPY 收益、成交量 z-score、63 日回撤、21 日年化波动和 `market_score`。线上 weekly/monthly/publish workflow 会自动生成该文件，再传给报告生成器。

可选代理参数：

- `--proxy-urls`：逗号或换行分隔的代理列表。
- `--proxy-list`：本地代理列表文件。
- `--proxy-pool-url`：公共代理池文本 URL，一行一个代理。

线上 workflow 也支持仓库变量 `MARKET_DATA_PROXY_URLS` 和 `MARKET_DATA_PROXY_POOL_URL`。脚本会先直连 Yahoo，失败后再尝试代理；日志只记录代理序号，不输出代理完整地址。

Yahoo chart 下载只是当前无依赖的免费行情入口；如果不可用，脚本会退回到 `theme_momentum_snapshot.json` 里的价格动量信息，报告仍能生成。免费公共代理池可以作为应急补充，但不应当作稳定生产数据源；它有稳定性、数据污染、封禁、隐私和合规风险。更稳的做法是使用本组织已有价格快照、缓存文件，或可审计的自有代理/数据源。
