# QuantAdvisorResearch


## QSL 架构角色

- **层级**：`研究/证据`。
- **职责**：研究型 advisory 发布系统。
- **事实源/归属**：可追溯 advisory reports 和 web/RSS 证据摘要。
- **消费对象**：公开 web/RSS 输入和 research signal context。
- **禁止事项**：自动提交订单、allocation changes 或账户建议。

[English README](README.md)

> 投资有风险。本项目不构成投资建议，仅用于学习、研究和工程审阅。

## 这个仓库是什么

QuantAdvisorResearch 是 QuantStrategyLab 的研究发布系统。基于网页和 RSS 证据发布研究型内容，不执行订单。

它产出研究、审计或编排类 artifact，不应自行提交券商订单，也不应直接修改 live allocation。

## 输出边界

- 生成报告应作为证据或审阅材料，不是自动交易指令。
- 保留来源可追溯性和 artifact 时间戳。
- 输出用于下游策略或平台改动前，需要人工 review。
- 凭据、私人数据和外部服务 token 不能提交到 Git，也不能写入日志。

## 仓库结构

- `src/`：库代码和运行时代码。
- `tests/`：单元测试、契约测试和回归测试。
- `docs/`：运行手册、设计说明、证据和集成契约。
- `.github/workflows/`：CI、定时任务、发布或部署 workflow。
- `scripts/`：运维脚本和本地辅助工具。

## 快速开始

```bash
python -m pip install -e .
python -m pytest -q
```

## 延伸文档

- [`docs/advisory_contract.md`](docs/advisory_contract.md)
- [`docs/data_factor_roadmap.md`](docs/data_factor_roadmap.md)
- [`docs/data_factor_roadmap.zh-CN.md`](docs/data_factor_roadmap.zh-CN.md)
- [`docs/notification_format.md`](docs/notification_format.md)
- [`docs/notification_format.zh-CN.md`](docs/notification_format.zh-CN.md)
- [`docs/system_design.md`](docs/system_design.md)
- [`docs/system_design.zh-CN.md`](docs/system_design.zh-CN.md)

## 社区和安全

- 贡献前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)，确认 PR 范围、本地校验和文档要求。
- 讨论、issue 和 review 请遵守 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。
- 涉及密钥、自动化、券商/交易所或云资源的漏洞请按 [SECURITY.md](SECURITY.md) 私密报告；不要为 secret 或实盘风险开公开 issue。

## 许可证

详见 [LICENSE](LICENSE)。
