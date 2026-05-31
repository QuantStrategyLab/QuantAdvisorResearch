# 智慧投顾研究系统设计

[English](system_design.md) | [简体中文](system_design.zh-CN.md)

## 当前架构理解

QuantStrategyLab 现有仓库已经天然分层：

- `PoliticalEventTrackingResearch`：事实事件层。
- `ResearchSignalContextPipelines`：研究信号上下文层，包含中线主题动量和长周期 AI shadow 背景。
- `QuantStrategyPlugins`：sidecar 风控、事件和通知 artifact 层。
- 券商平台仓库：执行、通知、凭证和运行时适配层。

`QuantAdvisorResearch` 只协调事件证据和 AI shadow context，不侵入其他量化策略、快照或券商执行仓库。

## 智慧投顾研究数据流

```text
PoliticalEventTrackingResearch
        |
        v
event evidence + source confidence
        |
        v
QuantAdvisorResearch <--- ResearchSignalContextPipelines latest_signal.json
        |
        v
intelligent-advisory artifact
        |
        v
GitHub Issue / Markdown / static HTML / RSS / manual review
```

当前不接入：

```text
UsEquitySnapshotPipelines
UsEquityStrategies
broker platform repositories
```

这些仓库保持独立，避免把政策/新闻/AI 驱动的推荐系统扩成全量量化平台。

## 设计模式

- Ports and Adapters：隔离事件来源和 AI shadow context。
- Strategy：不同推荐规则可替换，如事件驱动、政策资金、公开点名、风险暂缓。
- Pipeline：输入载入、候选聚合、评分、风控、报告渲染分阶段执行。
- Repository：保存 point-in-time 智慧投顾研究 artifact，用于后续 replay。
- Command：日评、周评、月评、历史回顾都用可审计命令触发。
- Specification：把“允许非个性化智慧投顾研究输出”“不能下单”“不能给账户级仓位”的政策写成显式规则。

## 不推荐方案

不建议把 `PoliticalEventTrackingResearch` 和 `ResearchSignalContextPipelines` 合并：

- 事实与模型观点混在一起会降低可审计性。
- 事件高频、AI 长周期，两者 cadence 不同。
- 未来出错时很难判断是事实错误、模型判断错误还是策略规则错误。

不建议直接接券商仓库：

- 会模糊“智慧投顾研究结论”与“执行”边界。
- 容易把智慧投顾研究 artifact 误用成 target allocation。
- 增加合规和操作风险。

也不建议在当前阶段接入 `UsEquitySnapshotPipelines` 或 `UsEquityStrategies`：

- 当前产品目标是政策/新闻/AI 驱动的智慧投顾研究，不是全量多因子选股。
- 接入策略仓库会让“推荐结论”和“可执行策略”边界变模糊。
- 接入快照仓库会引入数据 freshness、样本外回测和因子版本管理问题，MVP 过重。

## MVP 验证标准

- 能读取政治事件 CSV 和 AI shadow JSON。
- 能生成 `model_recommendations` 智慧投顾研究 JSON artifact。
- 能生成 `<output-json>.manifest.json`，记录 contract version、hash、Git SHA 和来源。
- 能生成周度公开智慧投顾研究报告，并保留日/月 cadence 的手工生成能力。
- 能生成静态 HTML 和 RSS feed 供非个性化订阅。
- 所有 artifact 明确允许非个性化智慧投顾研究输出，但禁止下单、调仓、账户级仓位和个性化建议。
- 后续可以 replay 历史智慧投顾研究结论，而不是重写过去判断。

数据源和因子完善路线见 [data_factor_roadmap.zh-CN.md](data_factor_roadmap.zh-CN.md)。

## 发布频率

当前不把公开推荐改成月更。原因是模型合同仍包含短线 `1-10个交易日` 和中线 `2-12周`，月更会让短线结论失效。

推荐节奏是：

- `PoliticalEventTrackingResearch`：事件/RSS 事实层周更，必要时手工触发；
- `ResearchSignalContextPipelines`：主题动量周更，长周期 AI shadow signal 月更；
- `QuantAdvisorResearch`：公开 HTML/JSON/RSS 智慧投顾研究继续周更；
- 月度复盘单独生成 artifact，用来回顾本月最终推荐和相对上次变化，不替代周度公开推荐。

## 跨板块长期主题层

`ResearchSignalContextPipelines` 的主题上下文不应只覆盖 AI。当前设计使用静态、版本化 taxonomy，把 AI、半导体、数据中心电力、网络安全、国防、能源、金融、医疗、消费平台、工业自动化、crypto 和 EV/汽车等板块统一成主题暴露。

`QuantAdvisorResearch` 可以读取 AI shadow artifact 中的：

```text
theme_bias
symbol_theme_exposure
```

但使用边界保持不变：主题 bias 只能作为研究背景和轻量评分输入，不能绕过事件证据、来源质量、风险提示和非个性化/不执行的合约约束。这样可以避免因为近期热点临时修改 universe 或权重，从而降低类似量化回测过拟合的问题。


## 短中长线来源分工

- 短线（1-10 个交易日）：事件事实层 + 市场确认共同负责。事件来自 `PoliticalEventTrackingResearch`，市场确认由本仓库生成，主要看相对强度、成交量、回撤和波动。
- 中线（2-12 周）：主题上下文层负责，`ResearchSignalContextPipelines` 的 `theme_momentum_snapshot.json` 标记为 `medium_horizon_theme_context`，主要看主题动量和个股动量。
- 长线（1-3 年）：AI shadow 背景层负责，来自 `latest_signal.json` 和 `signal_history/*.json`。

`QuantAdvisorResearch` 只在最后做确定性合成，报告中的 `supporting_context`、`horizon_scores` 和 `horizon_actions` 会记录每个最终推荐用到了短线、中线、长线哪些输入，以及每个周期是否达到推荐或观察门槛。
报告 summary 还会记录长线背景是否可用，避免把“上游 artifact 缺字段”误读成“长线没有机会”。

## Theme momentum 展示边界

`QuantAdvisorResearch` 可以消费 `theme_momentum_snapshot.json`，用途分两层：

- 公开页面只展示最终推荐，不展示主题候选池；
- 公开页面按长线 / 中线 / 短线三列展示，每列内按对应周期分数排序；
- 只要最终推荐通过某个周期的推荐或观察门槛，就在该周期栏渲染完整卡片；同一标的可以同时出现在多个周期栏；
- JSON/Markdown 保留 `theme_first_candidates[]` 供审计；
- `final_decisions` 可以把主题动量作为中线评分的重要输入；
- 基础 `recommendations[]` 评级仍由事件、watchlist 和 AI 背景生成；
- 不生成仓位、目标股数或执行策略。

如果上游 `ResearchSignalContextPipelines` 没有生成该 snapshot，workflow 会跳过该输入，报告仍可正常生成。

`market_confirmation.csv` 是可选输入，但线上 workflow 默认会自动生成。短线门槛要求有市场确认；中线门槛以主题动量和个股动量为主；长线门槛要求 AI shadow 或长期上下文足够强。

Yahoo chart 只能作为当前无依赖行情入口。随机免费代理 IP 池不应进入稳定生产链路；如果需要代理，应使用自控代理或更稳定的数据快照，并记录来源、时间和 hash，便于 replay。
