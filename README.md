# QuantAdvisorResearch

[Chinese README](README.zh-CN.md)

> Investing involves risk. This project does not provide investment advice and is for education, research, and engineering review only.

## What this repository is

QuantAdvisorResearch is a QuantStrategyLab research publishing system. It publishes research-oriented advisory content from web and RSS evidence without placing orders.

It produces research, audit, or orchestration artifacts. It should not submit broker orders or mutate live allocations by itself.

## Output boundary

- Treat generated reports as evidence or review material, not automatic trading instructions.
- Keep source traceability and artifact timestamps visible.
- Require human review before using outputs in downstream strategy or platform changes.
- Keep credentials, private data, and external service tokens out of Git and logs.

## Repository layout

- `src/`: library and runtime code.
- `tests/`: unit, contract, and regression tests.
- `docs/`: runbooks, design notes, evidence, and integration contracts.
- `.github/workflows/`: CI, scheduled jobs, release, or deployment workflows.
- `scripts/`: operator scripts and local helpers.

## Quick start

```bash
python -m pip install -e .
python -m pytest -q
```

## Useful docs

- [`docs/advisory_contract.md`](docs/advisory_contract.md)
- [`docs/data_factor_roadmap.md`](docs/data_factor_roadmap.md)
- [`docs/data_factor_roadmap.zh-CN.md`](docs/data_factor_roadmap.zh-CN.md)
- [`docs/notification_format.md`](docs/notification_format.md)
- [`docs/notification_format.zh-CN.md`](docs/notification_format.zh-CN.md)
- [`docs/system_design.md`](docs/system_design.md)
- [`docs/system_design.zh-CN.md`](docs/system_design.zh-CN.md)

## License

See [LICENSE](LICENSE).
