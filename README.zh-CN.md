# QuantAdvisorResearch

[English](README.md) | [简体中文](README.zh-CN.md)

QuantStrategyLab 的“智慧顾投”研究协调仓库。它只生成非个性化的研究建议、证据摘要和日/周/月复盘，不下单、不管理仓位、不接券商凭证。

## 仓库定位

这个仓库把各个研究仓库的产物组合成 advisory artifact：

- `PoliticalEventTrackingResearch`：政治/公开事件事实、催化剂、来源置信度。
- `AiLongHorizonSignalPipelines`：已保存的长周期 AI shadow context。
- `UsEquitySnapshotPipelines`：未来接入特征快照、候选排名、回测证据。
- `UsEquityStrategies`：继续负责确定性策略规则，不被本仓库替代。
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

输出包括：

- 候选标的
- 建议动作：观察、来源复核、研究候选、回避/延后
- 中长线投机/价值/事件驱动风格标签
- 证据分数和风险分数
- 主要理由、风险、复核清单
- 日/周/月复盘 cadence

## 边界

本仓库负责：

- advisory artifact schema
- 确定性评分和复核规则
- 日/周/月报告生成
- 历史建议记录和后续复盘入口

本仓库不负责：

- 券商 API、下单、调仓
- 目标仓位、目标股数、账户级资产配置
- 投资者适当性判断
- 模型 provider 路由或 prompt 执行
- 付费行情原始数据再分发

## 合规提醒

“不下单、不管仓位”会降低执行风险，但不自动消除投顾/推荐监管风险。只要面向投资者提供具体证券推荐，在不同商业模式下仍可能触发投资顾问、经纪推荐、适当性或 Reg BI 义务。

因此当前默认：

- `execution_allowed=false`
- `portfolio_allocation_allowed=false`
- `personalized_advice_allowed=false`
- `audience_scope=non_personalized_research`

## 测试

```bash
python -m pytest -q
```

## 周度复盘

`.github/workflows/weekly_advisory_review.yml` 会 checkout 本仓库、`PoliticalEventTrackingResearch`
和 `AiLongHorizonSignalPipelines`，生成周度 `recommendation_only` 报告并上传为 GitHub Actions artifact。

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
`.github/workflows/publish_advisory_site.yml` 可以在仓库启用 GitHub Pages 后部署同样的输出。
