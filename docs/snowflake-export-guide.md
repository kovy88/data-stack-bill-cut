# Snowflake scan: what to export (client guide)

The scan needs seven small CSV exports from your Snowflake account. Files 5–7 are optional; without them the warehouse and storage checks still run. You run them yourself in
Snowsight; no user, password or key is shared with us. The exports contain **metadata only**:
warehouse settings, hourly credits, query timings and table sizes. No row of your table data is
read.

Time needed: about 15 minutes.

## Steps

1. Open a new SQL worksheet in Snowsight.
2. Use a role that can read `SNOWFLAKE.ACCOUNT_USAGE` and see all warehouses, usually
   `ACCOUNTADMIN`. A custom role with `IMPORTED PRIVILEGES` on the `SNOWFLAKE` database is enough
   for files 2–4, but `SHOW WAREHOUSES` (file 1) only lists warehouses that role has a privilege on.
3. Run each query below, then use **Download results → CSV** and save the file under the name shown.
4. Send the files through the channel agreed in the NDA (not by plain e-mail).

| # | File name | What it contains |
|---|---|---|
| 1 | `warehouses.csv` | `SHOW WAREHOUSES`: size, auto-suspend, cluster counts |
| 2 | `warehouse_metering_history.csv` | credits per warehouse per hour, last 30 days |
| 3 | `query_history.csv` | per query: warehouse, start/end, execution time, bytes scanned, spilling |
| 4 | `table_storage_metrics.csv` | per table: active, time travel and fail-safe bytes |
| 5 | `metering_daily_history.csv` | daily cloud-services credits and the 10% adjustment |
| 6 | `automatic_clustering_history.csv` | reclustering credits per table |
| 7 | `materialized_view_refresh_history.csv` | materialized-view refresh credits |

The SQL files are generated with:

```bash
uv run data-stack-bill-cut snowflake sql --out snowflake_export_sql --days 30
```

They are also in `src/data_stack_bill_cut/snowflake/sql/` (the `{{DAYS}}` placeholder is replaced
by the command).

## Notes

- **Query text.** `query_history.csv` keeps only the first 120 characters of each query, used to
  label repeated patterns. To leave text out completely, replace that line with
  `NULL AS query_text_prefix`. The scan works the same; the pattern table then shows hashes.
- **Large accounts.** If the query history download is too big for Snowsight, shorten the window
  to 14 days in both the metering and the query history file (`--days 14`), or export with SnowSQL.
- **Excel.** Send the file Snowsight downloaded. If it is re-saved from a Czech Excel (semicolon,
  decimal comma, `D.M.YYYY`), the scan still reads it, but a timestamp it cannot parse is skipped
  and called out in the report.
- **Account usage latency.** ACCOUNT_USAGE views lag real time by up to a few hours; the queries
  stop at yesterday midnight so the window is complete.
- **Prices.** Tell us your price per credit and per TB-month of storage from your contract or
  invoice. The saving is priced with your numbers, not list prices.

## What happens next

1. We run the scan and send a written report with a USD saving number per finding, the exact
   `ALTER` statements, and the risks of each change (sample: `docs/sample-report.md`).
2. You decide what to apply. Every warehouse change is one reversible statement.
3. After 60–90 days you re-run the same four exports and we compare them with the baseline in the
   report (sample: `docs/sample-verification.md`). The fee is based on that verified number.
