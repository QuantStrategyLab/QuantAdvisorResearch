## Repository guardrails

- This repository is non-personalized model recommendation infrastructure. Do not add broker credentials, order placement, live allocation, or account-specific portfolio management.
- Prefer targeted tests and synthetic inputs. Scheduled advisory reviews use the repository's GitHub-hosted [monthly review workflow](../.github/workflows/monthly_advisory_review.yml).
- Do not commit raw licensed market data or private investor profile data.
- AI outputs are advisory context only. They must not directly create orders, target quantities, or portfolio weights.
