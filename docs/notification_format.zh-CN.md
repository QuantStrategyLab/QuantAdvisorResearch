# 模型推荐通知格式

## 设计原则

通知可以明确展示“推荐什么标的、为什么、适合短中长哪类周期”。边界不是禁止推荐，而是禁止把模型推荐变成账户级操作：

- 可以输出非个性化模型推荐、观察、来源核验、暂缓。
- 可以输出适合周期：短线、中线、长线。
- 可以输出理由、风险、证据来源和模型分数。
- 不输出目标仓位、股数、订单类型、账户调仓或个性化适当性结论。
- 不自动触发券商下单。

## 通用字段

```text
as_of
cadence
mode = model_recommendations
audience_scope = non_personalized_model_research
policy.non_personalized_recommendations_allowed = true
policy.execution_allowed = false
policy.portfolio_allocation_allowed = false
policy.account_specific_advice_allowed = false
recommendations[]
```

每条 `recommendations[]` 用同一组字段渲染：

```text
symbol
name
rating
rating_label
recommendation_tier
recommendation_tier_label
primary_horizon
primary_horizon_label
primary_horizon_window
horizon_note
suitable_horizons[]
suitable_horizon_windows{}
strategy_style
score
evidence_score
risk_score
source_confidence
source_confidence_label
reasons[]
risk_notes[]
evidence_refs[]
review_checklist[]
```

## RSS 摘要

RSS 只放最短摘要，适合订阅器扫一眼：

```text
标题：2026-05-30 周度模型推荐
摘要：模式=model_recommendations；来源=operator_supplied；主题=...；推荐=EVT1, EVT2。
     非个性化模型输出；不包含下单、仓位配置或账户级建议。
链接：完整 HTML 报告
```

## Telegram 摘要

Telegram 适合中等长度，最多展示前 3-5 个推荐：

```text
量化模型推荐 | 周度 | 2026-05-30

模式：model_recommendations
来源：operator_supplied
来源事件：8

主题动量：
- #1 hbm_memory 分数=2.16 标的=MU

主题优先候选：
- #1 MU | hbm_memory | 动量=2.93 | 主题候选 | 待事件确认

推荐摘要：
- EVT1 | 一级推荐 | 重点推荐 | 中线 | 分数=0.85
- EVT2 | 一级推荐 | 重点推荐 | 中线 | 分数=0.83

说明：非个性化模型输出；不包含下单、仓位配置或账户级建议。
完整报告：<HTML link>
```

## 邮件摘要

邮件可以放完整列表和复核清单，结构建议：

```text
Subject: 量化模型推荐周度复盘 - 2026-05-30

1. 本期推荐摘要
2. 重点推荐
3. 观察名单
4. 先核验来源
5. 暂缓/风险项
6. 证据链接
7. 下期复核清单
```

## 推荐等级

- `recommend` / 重点推荐：模型证据较集中，适合进入投资者可读推荐列表。
- `watch` / 观察：有线索但还需要更多事件、基本面或价格证据。
- `verify_source` / 先核验来源：低置信来源，不应升级为推荐。
- `defer` / 暂缓：风险或负面 shadow context 优先。
- `monitor` / 监控：只保留上下文，不进入推荐区。

## 推荐层级

- `tier_1` / 一级推荐：推荐等级为重点推荐，分数和来源可信度同时满足发布条件。
- `tier_2` / 二级推荐：推荐等级为重点推荐，但来源或分数还需要更多确认。
- `watchlist` / 观察名单：保留观察，不作为重点推荐。
- `source_check` / 来源核验：先确认来源再决定是否升级。
- `defer` / 暂缓：风险优先。
- `monitor` / 监控：上下文保留。

## 周期原则

- 主周期只给一个：短线、中线、长线或不适用。
- 周期窗口必须固定显示：
  - 短线：`1-10个交易日`
  - 中线：`2-12周`
  - 长线：`1-3年`
- 事件驱动默认以中线为主，短线只作为催化反应观察，不作为自动交易触发。
- 长线推荐主窗口为 `1-3年`，需要更多基本面、AI shadow 和事件持续性支持；超过 3 年应通过年度复盘确认逻辑仍成立。
- `primary_horizon_window` 必须给出主周期时间范围。
- `suitable_horizon_windows` 必须给出所有可观察周期的时间范围。
- `horizon_note` 必须解释为什么适合该周期，以及短线风险在哪里。

## 禁用表达

通知中不要使用：

- 目标仓位、目标股数、自动建仓、自动加仓、自动减仓。
- 账户级短语，例如“适合你的账户”“你应该买入多少”。
- 确定性收益，例如“稳赚”“保证上涨”。

允许使用：

- 重点推荐、观察、暂缓。
- 短线、中线、长线。
- 模型分数、证据分数、风险分数。
- 推荐理由、来源核验、估值复核、财报复核。

## 当前已实现渠道

- GitHub Pages：`.github/workflows/publish_advisory_site.yml` 发布 HTML、JSON、Markdown 和 RSS。
- RSS：`scripts/publish_advisory_site.py` 生成 `feed.xml`。
- Telegram：可选。如果仓库 secrets 配置了 `TELEGRAM_BOT_TOKEN` 和 `TELEGRAM_CHAT_ID`，`scripts/notify_advisory_telegram.py` 会在 Pages 部署成功后发送短摘要；如果缺少任一 secret，会跳过通知但不让发布失败。

通知仍然只能包含标的、主题优先候选、推荐层级、周期、来源事件数、主题动量、模型分数、理由、风险和完整报告链接；不能包含订单、目标仓位、目标股数、账户适当性或账户级配置建议。
