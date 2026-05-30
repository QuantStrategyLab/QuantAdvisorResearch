# QuantAdvisorResearch

[English](README.md) | [简体中文](README.zh-CN.md)

QuantStrategyLab 的“智慧顾投”研究协调仓库。它生成非个性化模型推荐、推荐理由、适合周期和日/周/月复盘，不下单、不管理仓位、不接券商凭证。

线上站点：<https://quantstrategylab.github.io/QuantAdvisorResearch/>

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
- 推荐等级：重点推荐、观察、先核验来源、暂缓、监控
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

通知格式设计见 [docs/notification_format.zh-CN.md](docs/notification_format.zh-CN.md)。
数据源和因子完善路线见 [docs/data_factor_roadmap.zh-CN.md](docs/data_factor_roadmap.zh-CN.md)。
