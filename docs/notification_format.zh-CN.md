# 研究雷达通知格式

## 设计原则

通知只做研究雷达提醒，不做直接股票推荐。任何渠道都必须保留以下边界：

- 不输出买入、卖出、持有评级。
- 不输出目标价、仓位、股数、止盈止损或账户动作。
- 不触发券商下单、调仓或个性化适当性判断。
- 只输出证据摘要、风险、复核状态和下一步研究动作。

## 通用字段

```text
as_of
cadence
mode = research_radar
audience_scope = non_personalized_research
policy.direct_stock_recommendation_allowed = false
policy.execution_allowed = false
research_items[]
```

每条 `research_items[]` 用同一组字段渲染：

```text
symbol
name
review_status
research_view
research_lens
research_priority
evidence_score
risk_score
evidence_summary
risks[]
review_checklist[]
evidence_refs[]
not_investment_rating = true
```

## RSS 摘要

RSS 只放最短摘要，适合订阅器扫一眼：

```text
标题：2026-05-30 Weekly Research Radar
摘要：Mode=research_radar; audience=non_personalized_research;
     review queue=EVT1, EVT2, EVT3.
     No buy/sell/hold rating, execution, or portfolio allocation.
链接：完整 HTML 报告
```

## Telegram 摘要

Telegram 适合中等长度，最多展示前 3-5 个研究项：

```text
Quant Research Radar | Weekly | 2026-05-30

Policy: no buy/sell/hold rating, no execution, no allocation.

1. EVT1 | evidence_review | priority 0.85
   Evidence: disclosure_buy, public_mention, AI shadow watch.
   Risk: unresolved AI data gaps.
   Next: verify source freshness, valuation, earnings calendar.

2. EVT3 | verify_source | priority 0.38
   Evidence: low-confidence disclosure lead.
   Risk: source must be verified before any strategy review.

Full report: <HTML link>
```

## 邮件摘要

邮件可以放完整复核清单，结构建议：

```text
Subject: Quant Research Radar Weekly Review - 2026-05-30

1. Policy Boundary
2. Executive Research Queue
3. Top Research Items
4. Source Verification Items
5. Risk-Deferred Items
6. Evidence Links
7. Review Checklist
```

## 状态含义

- `evidence_review`：证据较集中，进入研究复核队列；不是买入建议。
- `verify_source`：来源置信度不足，只能做来源核验。
- `observe`：保留观察，等待新增事件、基本面或价格证据。
- `risk_defer`：风险或负面 shadow context 优先，暂不升级研究。
- `context_monitor`：上下文监控，不形成研究队列。

## 禁用表达

通知中不要使用：

- 买入、卖出、持有、强烈推荐。
- 目标价、仓位、建仓、加仓、减仓。
- 胜率、稳赚、确定性收益。
- 个性化短语，例如“你应该”“适合你的账户”。

允许使用：

- 研究优先级。
- 证据分数、风险分数。
- 来源核验、事件复核、估值复核。
- 非个性化研究线索。
