# 智慧顾投研究系统设计

## 当前架构理解

QuantStrategyLab 现有仓库已经天然分层：

- `PoliticalEventTrackingResearch`：事实事件层。
- `AiLongHorizonSignalPipelines`：AI 长周期 shadow 观点层。
- `QuantStrategyPlugins`：sidecar 风控、事件和通知 artifact 层。
- 券商平台仓库：执行、通知、凭证和运行时适配层。

`QuantAdvisorResearch` 只协调事件证据和 AI shadow context，不侵入其他量化策略、快照或券商执行仓库。

## 模型推荐数据流

```text
PoliticalEventTrackingResearch
        |
        v
event evidence + source confidence
        |
        v
QuantAdvisorResearch <--- AiLongHorizonSignalPipelines latest_signal.json
        |
        v
model-recommendation artifact
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
- Repository：保存 point-in-time model recommendation artifact，用于后续 replay。
- Command：日评、周评、月评、历史回顾都用可审计命令触发。
- Specification：把“允许非个性化模型推荐”“不能下单”“不能给账户级仓位”的政策写成显式规则。

## 不推荐方案

不建议把 `PoliticalEventTrackingResearch` 和 `AiLongHorizonSignalPipelines` 合并：

- 事实与模型观点混在一起会降低可审计性。
- 事件高频、AI 长周期，两者 cadence 不同。
- 未来出错时很难判断是事实错误、模型判断错误还是策略规则错误。

不建议直接接券商仓库：

- 会模糊“模型推荐”与“执行”边界。
- 容易把 model recommendation artifact 误用成 target allocation。
- 增加合规和操作风险。

也不建议在当前阶段接入 `UsEquitySnapshotPipelines` 或 `UsEquityStrategies`：

- 当前产品目标是政策/新闻/AI 驱动的模型推荐，不是全量多因子选股。
- 接入策略仓库会让“推荐结论”和“可执行策略”边界变模糊。
- 接入快照仓库会引入数据 freshness、样本外回测和因子版本管理问题，MVP 过重。

## MVP 验证标准

- 能读取政治事件 CSV 和 AI shadow JSON。
- 能生成 `model_recommendations` JSON artifact。
- 能生成 `<output-json>.manifest.json`，记录 contract version、hash、Git SHA 和来源。
- 能生成日/周/月 Markdown 复盘。
- 能生成静态 HTML 和 RSS feed 供非个性化订阅。
- 所有 artifact 明确允许非个性化模型推荐，但禁止下单、调仓、账户级仓位和个性化建议。
- 后续可以 replay 历史模型推荐，而不是重写过去判断。

数据源和因子完善路线见 [data_factor_roadmap.zh-CN.md](data_factor_roadmap.zh-CN.md)。
