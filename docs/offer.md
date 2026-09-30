# Snowflake bill cut: pay only for savings you can see on the invoice

For data teams whose Snowflake bill grew faster than their workload.
Best fit: warehouse compute of roughly USD 50k+ per year (below that the fee rarely justifies
your time).

## How it works

1. **Free scan.** You run four read-only exports in Snowsight (about 15 minutes, guide:
   `docs/snowflake-export-guide.md`), or we do it together on a 90-minute call. No credentials
   are shared and no table data is read.
2. **Written saving number within 2 business days.** One report with a USD figure per finding,
   priced at *your* contract rate, the exact `ALTER` statement for each change, and its risks.
   Sample on a synthetic account: [the report](sample-report.html).
3. **You apply what you agree with.** Most changes are one reversible statement each. We can do
   it together on a call.
4. **Verification after 60–90 days.** You re-run the same exports; we compare credits per day
   and per 1,000 queries against the baseline in the report. Sample: [the invoice check](sample-verification.html).
5. **Fee: 25 % of the verified annual saving, invoiced once.** No verified saving, no fee.
   If your procurement needs a fixed price: small fixed audit fee plus a lower share.

## What the scan checks

- Warehouses that are billed but run no queries
- Idle time billed after the last query before auto-suspend kicks in, modelled per warehouse
  from your own query history and checked against metered credits
- Warehouses one size larger than their queries need (short queries, no spilling)
- Permanent tables rebuilt every day that pay for 7 days of fail-safe per version
- The most expensive repeated query patterns (not counted as saving; input for your team)
- Cloud services billed above the included 10% of compute, and clustering or materialized-view refresh on objects that never appear in the query export (two extra CSVs)

Every number in the report comes from your account's data. Nothing is extrapolated from other
clients or industry averages.

Snowflake is automated today. Next: AWS GPU / SageMaker instances, BigQuery, Datadog logging.

## Data handling

- Read-only: exports are metadata from `SNOWFLAKE.ACCOUNT_USAGE` and `SHOW WAREHOUSES`.
- Query text is cut to 120 characters and can be left out entirely.
- NDA before any export (`docs/nda.md`); files are kept only for the engagement and deleted after verification.

## Contact

Matěj Koval, data scientist. koval.matej88@seznam.cz
