# Data Stack Bill Cut

Success-fee audit of data/ML cloud spend: Snowflake/BigQuery, GPU & ML instances (SageMaker), logging/observability (Datadog), storage. Niche chosen because it fits a data-science background; generic AWS auditing is saturated (Upwork ~30 USD/h median, Premier Partners doing free audits).

## Business context
- Offer: free 90-min read-only scan -> written USD saving number. Then 25 % of verified annual saving, payable after verification on the invoice at 60–90 days.
- Scope: Snowflake or BigQuery, GPU/ML instances, logging, storage.
- Weakness to fix first: no AWS certification, no reference clients -> get AWS Cloud Practitioner / SA Associate, publish 2 articles with concrete numbers (one Snowflake warehouses, one GPU instances), build references from free scans.
- Proof of saving: Cost Explorer / Snowflake account usage before vs after, verified after 60–90 days.
- Market evidence (verify before quoting): Flexera 2026 ~29 % cloud waste; ChartMogul cut Snowflake bill 70 %; CBTW saved a client 112k USD/yr on Datadog in 6 weeks.
- Cash-flow risk: success fees mean waiting 30–90 days. For first contract combine small fixed fee + share.

## Rules
- Read-only access only; NDA; never commit client data (`data/private/`).
- Do not trust vendor docs prose for cost-export schemas (Snowflake ACCOUNT_USAGE views, AWS CUR, GCP billing export) — verify against real exports / maintained open-source tooling first.
- Never promise average savings; quote only from the client's own data.
- Employer Generali: no insurance clients, no employer data; check contract re: side activity.

## Stack
Python 3.12, uv, pandas, pytest, ruff (`uv run ...`). API -> FastAPI. Never pip directly.

## Layout
- `src/data_stack_bill_cut/` — scanners (one module per platform)
- `docs/` — offer, scan checklists, 30-day plan
