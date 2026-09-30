# Snowflake saving verification: Demo Co (synthetic)

Before: 2026-08-29 to 2026-09-28 (30 days). After: 2026-11-27 to 2026-12-27 (30 days). Generated 2026-09-29. Price: 3.00 USD per credit.

## Result

| Measure | Annual saving | Fee (25%) |
| --- | ---: | ---: |
| Raw (credits per day) | **$76,503** | $19,126 |
| Workload-adjusted (credits per 1,000 queries) | **$85,231** | $21,308 |

Raw compares credits per day. Workload-adjusted compares credits per 1,000 queries and prices the difference at the after-period query volume, so growth in usage does not hide the saving and a drop in usage does not inflate it. The contract states which measure is invoiced.

## Per warehouse

| Warehouse | Credits/day before | after | Queries/day before | after | Credits/1k q before | after | Raw annual | Adjusted annual |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| LEGACY_REPORTING_WH | 24.0 | 0.0 | 0 | 0 | – | – | $26,280 | $26,280 |
| TRANSFORM_WH | 75.9 | 62.6 | 1,680 | 1,680 | 45.16 | 37.25 | $14,554 | $14,554 |
| LOADING_WH | 19.3 | 6.1 | 576 | 576 | 33.44 | 10.55 | $14,443 | $14,443 |
| DS_WH | 16.4 | 4.0 | 14 | 15 | 1,183.94 | 271.47 | $13,584 | $14,621 |
| BI_WH | 44.9 | 37.9 | 1,152 | 1,332 | 38.98 | 28.47 | $7,642 | $15,332 |
