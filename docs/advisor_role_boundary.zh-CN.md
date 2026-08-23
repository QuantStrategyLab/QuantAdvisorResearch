# 顾问角色边界

`QuantAdvisorResearch` 的“顾投”不是账户级组合顾问，而是 **AssetIdeaAdvisor（标的研究顾问）**：

- 输出标的候选、研究理由、风险和观察建议；
- 保存可复核的研究 artifact；
- 不计算账户级仓位；
- 不选择 live 策略组合；
- 不连接 broker，也不生成订单。

账户级的 **PortfolioAdvisor（组合配置顾问）** 属于 QuantPlatformKit 的组合与风险层，负责根据资金、风险预算和允许资产范围生成组合建议。它可以消费本仓库的标的研究结果，但仍不直接开启 live。

```text
AssetIdeaAdvisor → 策略研究 → PortfolioAdvisor → Risk Gate → live decision
```

为兼容旧接口，仓库名和 `model_recommendations` artifact 暂不改名；新文档和新接口应使用 `AssetIdeaAdvisor`，避免把标的建议误认为完整智能顾投。
