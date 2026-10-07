## Repository guardrails

- This repository is non-personalized model recommendation infrastructure. Do not add broker credentials, order placement, live allocation, or account-specific portfolio management.
- Prefer targeted tests and synthetic inputs. When executing on the VPS, keep checks small and bounded for that host.
- Do not commit raw licensed market data or private investor profile data.
- AI outputs are advisory context only. They must not directly create orders, target quantities, or portfolio weights.
