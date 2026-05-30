## Repository guardrails

- This repository is non-personalized model recommendation infrastructure. Do not add broker credentials, order placement, live allocation, or account-specific portfolio management.
- Keep checks small and bounded on the VPS. Prefer targeted tests and synthetic inputs.
- Do not commit raw licensed market data or private investor profile data.
- AI outputs are advisory context only. They must not directly create orders, target quantities, or portfolio weights.
