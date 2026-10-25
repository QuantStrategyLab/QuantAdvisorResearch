# QuantAdvisorResearch

把公开网页与 RSS 证据转成可追溯研究型咨询报告的研究发布系统。

[English](README.md) | 简体中文

## 状态

实验性项目，使用风险自负。本项目不构成投资建议，也不保证任何交易结果。它的输出是研究证据，不是交易指令。

## 简介

QuantAdvisorResearch 基于公开网页与 RSS 证据构建并发布研究型咨询内容。它是咨询研究系统中的确定性合成层：把上游证据合成为咨询报告、市场确认与建议复核产物，以及一个静态站点，并保持每个输出都可追溯到来源。它面向需要查看已发布推理过程的研究者和审阅者，不面向实盘交易。

## 不适用范围

它不提交券商订单。它不改变仓位分配。它不产生自动交易指令或自动批准，其报告也不构成投资建议。

## 快速开始

需要 Python 3.11 或更高版本。

```bash
python -m pip install -e '.[test]'
python -m pytest -q
```

构建与发布入口使用 `--help` 打印用法和必填参数：

```bash
qar-build-advisory-artifacts --help
qar-build-advisory-report --help
qar-publish-advisory-site --help
```

## 配置

| 变量 | 必填 | 默认值 | 用途 |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | 否 | 无 | 发送咨询通知所用的 bot token。 |
| `TELEGRAM_CHAT_ID` | 否 | 无 | 接收咨询通知的会话。 |
| `NOTIFY_LANG` | 否 | `zh` | 通知使用的语言。 |

报告与通知契约见 [`docs/advisory_contract.md`](docs/advisory_contract.md) 和 [`docs/notification_format.md`](docs/notification_format.md)。

## 仓库结构

```
src/        库代码和命令实现
scripts/    命令行辅助脚本
docs/       设计说明与输出契约
examples/   示例输入
data/       本地工作输出
tests/      单元与契约测试
```

## 参与贡献

见 [CONTRIBUTING.md](CONTRIBUTING.md)。AI 助手与维护者遵循 [AGENTS.md](AGENTS.md)。

## 安全

见 [SECURITY.md](SECURITY.md)。安全漏洞不要开公开 issue，也不要让凭据、私有数据和外部服务 token 进入 Git 或日志。

## 许可证

MIT，见 [LICENSE](LICENSE)。
