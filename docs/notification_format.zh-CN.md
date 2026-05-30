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
horizon_note
suitable_horizons[]
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
标题：2026-05-30 Weekly Model Recommendations
摘要：Mode=model_recommendations; recommended=EVT1, EVT2.
     Non-personalized model output; no execution, allocation, or account-specific advice.
链接：完整 HTML 报告
```

## Telegram 摘要

Telegram 适合中等长度，最多展示前 3-5 个推荐：

```text
Quant Model Recommendations | Weekly | 2026-05-30

1. EVT1 | 一级推荐 | 重点推荐 | 中线 | 来源中 | score 0.85
   理由：公开事件 + 披露证据 + AI shadow 仍在观察区间。
   周期：事件驱动以中线验证为主；短线只适合观察催化反应，波动和反转风险更高。
   风险：AI 数据缺口未完全解决。

2. EVT2 | 一级推荐 | 重点推荐 | 中线 | 来源高 | score 0.83
   理由：政策资本事件触发，来源置信度高。
   风险：需要复核估值、财报日和最新价格行为。

完整报告：<HTML link>
```

## 邮件摘要

邮件可以放完整列表和复核清单，结构建议：

```text
Subject: Quant Model Recommendations Weekly Review - 2026-05-30

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
- 事件驱动默认以中线为主，短线只作为催化反应观察，不作为自动交易触发。
- 长线推荐需要更多基本面、AI shadow 和事件持续性支持。
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
