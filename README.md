# QuantAdvisorResearch

Research publishing system that turns public web and RSS evidence into traceable advisory reports.

English | [简体中文](README.zh-CN.md)

## Status

Experimental. Use at your own risk. This project is not financial advice and
does not guarantee any trading result. Its outputs are research evidence, not
trading instructions.

## What this is

QuantAdvisorResearch builds and publishes research-oriented advisory content
from public web and RSS evidence. It is the deterministic composition layer of
the advisory research system: it combines upstream evidence into advisory
reports, market-confirmation and recommendation-review artifacts, and a static
site, keeping each output traceable to its source. It is aimed at researchers
and reviewers who need the published reasoning, not at live trading.

## What this is not

It does not place broker orders. It does not change allocations. It does not
produce automatic trading instructions or auto-approvals, and its reports are
not investment advice.

## Quick start

Requires Python 3.11 or newer.

```bash
python -m pip install -e '.[test]'
python -m pytest -q
```

The build and publish entry points print usage and required arguments when run
with `--help`:

```bash
qar-build-advisory-artifacts --help
qar-build-advisory-report --help
qar-publish-advisory-site --help
```

## Configuration

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | No | none | Bot token used to send advisory notifications. |
| `TELEGRAM_CHAT_ID` | No | none | Chat that receives advisory notifications. |
| `NOTIFY_LANG` | No | `zh` | Language used for notifications. |

Report and notification contracts live in [`docs/advisory_contract.md`](docs/advisory_contract.md)
and [`docs/notification_format.md`](docs/notification_format.md).

## Repository layout

```
src/        library code and command implementations
scripts/    command-line helpers
docs/       design notes and output contracts
examples/   sample inputs
data/       local working output
tests/      unit and contract tests
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). AI assistants and maintainers also follow [AGENTS.md](AGENTS.md).

## Security

See [SECURITY.md](SECURITY.md). Do not open a public issue for a vulnerability.
Keep credentials, private data, and external service tokens out of Git and logs.

## License

MIT. See [LICENSE](LICENSE).
