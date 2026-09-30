# Data Stack Bill Cut

Read-only cost scans for data/ML cloud spend with a written USD saving number. Snowflake is
implemented; GPU/SageMaker, BigQuery and logging are next (see `docs/scan-checklist.md`).

## Snowflake workflow

```bash
# 1. Generate the export queries for the client (they run them in Snowsight, no credentials shared)
uv run data-stack-bill-cut snowflake sql --out snowflake_export_sql --days 30

# 2. Put the four CSVs in data/private/<client>/ (gitignored) and scan with the client's prices
uv run data-stack-bill-cut snowflake scan data/private/acme \
    --credit-price 3.00 --storage-price 23 --client "Acme" \
    --out data/private/acme/report.html
# A path ending in .md writes the same report as Markdown.

# 3. 60–90 days after the changes: same exports again, compare against the baseline
uv run data-stack-bill-cut snowflake verify \
    --before data/private/acme --after data/private/acme-after \
    --credit-price 3.00 --out data/private/acme/verification.html
```

Try it without a client on a synthetic account:

```bash
uv run data-stack-bill-cut snowflake demo-data --out data/samples/snowflake_demo
uv run data-stack-bill-cut snowflake scan data/samples/snowflake_demo --credit-price 3 --storage-price 23
```

Output from the demo data: `docs/sample-report.md`, `docs/sample-verification.md`.

## Checks (Snowflake)

| Check | Confidence | Saving |
|---|---|---|
| Warehouse billed with zero queries | high | its whole metered bill |
| Auto-suspend longer than target (default 60 s) | high | billing model: busy periods from QUERY_HISTORY + idle tail per suspension, calibrated against metered credits |
| One size smaller (short queries, no spilling) | low | range: idle credits halved … all credits halved; needs a 1-week test |
| High-churn permanent tables → transient | medium | fail-safe (+ time travel) bytes × storage price |
| Most expensive query patterns | – | informational |

Schemas were checked against maintained open-source tooling, not vendor prose:
`QUERY_HISTORY`, `WAREHOUSE_METERING_HISTORY` and credits per size against
[dbt-snowflake-monitoring](https://github.com/get-select/dbt-snowflake-monitoring);
`SHOW WAREHOUSES` columns against the
[Snowflake Terraform provider](https://github.com/snowflakedb/terraform-provider-snowflake);
`TABLE_STORAGE_METRICS` against
[md-migration-assessment](https://github.com/motherduckdb/md-migration-assessment).
Still to do: run once on a real account export.

## Development

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

## Docs

- `docs/offer.md`: client-facing one-pager
- `docs/snowflake-export-guide.md`: what the client exports and how
- `docs/article-auto-suspend.md`: publishable article (EN + CZ), synthetic numbers labeled as such
- `docs/outreach.md`: LinkedIn / e-mail / Upwork templates (EN + CZ)
- `docs/scan-checklist.md`, `docs/plan-30d.md`
