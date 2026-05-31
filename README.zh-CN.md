# QuantAdvisorResearch

[English](README.md) | [简体中文](README.zh-CN.md)

QuantStrategyLab 的“智慧顾投”研究协调仓库。它生成非个性化模型推荐、推荐理由、适合周期和日/周/月复盘，不下单、不管理仓位、不接券商凭证。

线上站点：<https://quantstrategylab.github.io/QuantAdvisorResearch/>

当前运行节奏是：**周度公开推荐 + 周度事件/主题刷新 + 月度 AI shadow 背景**。后续可以新增月度复盘，用来回顾上月推荐表现，但只要报告里仍保留短线 `1-10个交易日` 和中线 `2-12周` 窗口，公开推荐就不应改成月更。

## 仓库定位

这个仓库把事件研究和 AI shadow 产物组合成 model recommendation artifact：

- `PoliticalEventTrackingResearch`：政治/公开事件事实、催化剂、来源置信度。
- `AiLongHorizonSignalPipelines`：已保存的长周期 AI shadow context。
- 其他量化策略/快照仓库：保持独立，不作为当前推荐链路的直接输入。
- 各券商平台仓库：继续只负责执行链路；本仓库不调用它们。

## 当前 MVP

当前实现一个确定性报告生成器：

```bash
python scripts/build_advisory_report.py \
  --as-of 2026-05-30 \
  --cadence weekly \
  --political-events examples/political_events.example.csv \
  --political-watchlist examples/political_watchlist.example.csv \
  --ai-signal examples/ai_long_horizon_signal.example.json \
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

- Python 包版本：`0.1.1`
- 报告 schema：`schema_version = 5`
- 报告 contract：`model_recommendations.v5`
- 报告 manifest：`<output-json>.manifest.json`

manifest 会记录 JSON/Markdown 的 SHA256、`as_of`、cadence、来源 artifact、政策边界、Git SHA、GitHub run id 和 contract version。这样和快照/AI artifact 仓库保持同类版本纪律，但不会把推荐输出变成可执行策略 target。

## 来源模式

如果报告输入来自 `examples/`，输出会标记 `source_mode=fixture`，HTML/RSS 也会显示 fixture 警告，避免把合成样例误认为真实推荐。真实运营输入会标记为 `source_mode=operator_supplied`。

## 边界

本仓库负责：

- model recommendation artifact schema
- 确定性评分和复核规则
- 日/周/月报告生成
- 历史模型推荐记录和后续复盘入口

本仓库不负责：

- 券商 API、下单、调仓
- 目标仓位、目标股数、账户级资产配置
- 投资者适当性判断
- 模型 provider 路由或 prompt 执行
- 付费行情原始数据再分发

## AI 使用边界

本仓库不直接调用 Codex、OpenAI、Anthropic 或其他模型 API。它只读取 `AiLongHorizonSignalPipelines` 已保存的 `mode=shadow` artifact。

这三个仓库里，只有 `AiLongHorizonSignalPipelines` 的月度 shadow signal 流程会涉及 AI，而且模型执行也委托给 `QuantStrategyLab/CodexAuditBridge`。模型 API key 和 fallback provider routing 都应集中在那里，不应放到本仓库。

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
和 `AiLongHorizonSignalPipelines`，生成周度 `model_recommendations` 报告并上传为 GitHub Actions artifact。

它不会提交文件、不会通知投资者、不会创建订单。

`.github/workflows/publish_advisory_site.yml` 会每周发布 HTML/JSON/RSS 站点。如果仓库 secrets 配置了 `TELEGRAM_BOT_TOKEN` 和 `TELEGRAM_CHAT_ID`，Pages 部署成功后会发送一条非个性化 Telegram 摘要；如果没配置，通知步骤会跳过；Telegram 发送异常会记录在日志里，但不阻断网页/RSS 发布。

周度发布是有意保留的：短线结论如果只月更会过期；月度 AI shadow 只提供长周期背景，不作为每周追热点的模型输入。

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

当前公开页面、RSS 标题和 Telegram 摘要默认使用简体中文（`zh-CN`）。
JSON 字段名继续保持英文契约键，避免破坏下游程序读取。

发布真实来源时，workflow inputs 要切到 `PoliticalEventTrackingResearch` 内的真实 CSV：

```bash
gh workflow run "Publish Model Recommendations Site" \
  --repo QuantStrategyLab/QuantAdvisorResearch \
  -f as_of=2026-05-30 \
  -f political_events_path=data/live/political_events.csv \
  -f political_watchlist_path=data/live/political_watchlist.csv \
  -f ai_signal_path=data/output/latest_signal.json
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
  --ai-signal examples/ai_long_horizon_signal.example.json \
  --theme-momentum examples/theme_momentum_snapshot.example.json \
  --output-json data/output/advisory_report.example.json \
  --output-md data/output/advisory_report.example.md
```

主题动量会生成 `theme_first_candidates[]`，公开页面会把它展示为“本期重点股票池”。
股票池每期保留 5-10 个股票/公司标的，说明行业/主题背景、为什么入选、事件确认状态和主要风险。
这些候选按主题和个股动量排序，并标明是否已有事件确认；但它们仍然不直接改变推荐评级、分数、仓位或执行状态。
线上 workflow 如果找不到 `data/output/theme_momentum_snapshot.json`，会自动跳过这个展示区块。

Yahoo chart 下载只作为临时 fallback。不要把随机免费代理 IP 池作为稳定生产方案；它有稳定性、数据污染、封禁、隐私和合规风险。更稳的做法是使用本组织已有价格快照、缓存文件，或可审计的自有代理/数据源。
