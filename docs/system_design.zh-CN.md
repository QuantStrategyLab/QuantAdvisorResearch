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

## 跨板块长期主题层

`AiLongHorizonSignalPipelines` 的长期主题层不应只覆盖 AI。当前设计使用静态、版本化 taxonomy，把 AI、半导体、数据中心电力、网络安全、国防、能源、金融、医疗、消费平台、工业自动化、crypto 和 EV/汽车等板块统一成主题暴露。

`QuantAdvisorResearch` 可以读取 AI shadow artifact 中的：

```text
theme_bias
symbol_theme_exposure
```

但使用边界保持不变：主题 bias 只能作为研究背景和轻量评分输入，不能绕过事件证据、来源质量、风险提示和非个性化/不执行的合约约束。这样可以避免因为近期热点临时修改 universe 或权重，从而降低类似量化回测过拟合的问题。

## Theme momentum 展示边界

`QuantAdvisorResearch` 可以消费 `theme_momentum_snapshot.json`，但只用于报告展示：

- 展示当前强主题；
- 展示主题内 top symbols；
- 写入 `summary.top_theme_ids` 和 `theme_momentum.top_themes`；
- 不改变推荐评级、评分、周期、仓位或执行策略。

如果上游 `AiLongHorizonSignalPipelines` 没有生成该 snapshot，workflow 会跳过该输入，报告仍可正常生成。

Yahoo chart 只能作为临时 fallback。随机免费代理 IP 池不应进入稳定生产链路；如果需要代理，应使用自控代理或更稳定的数据快照，并记录来源、时间和 hash，便于 replay。
