# Scan checklist (draft — verify each query against the platform docs/real account)

## Snowflake
- [x] Warehouse sizing vs. actual query load; auto-suspend settings (`snowflake scan`: auto_suspend, downsize)
- [x] Idle credit burn (credits billed while no queries ran) (`snowflake scan`: idle_warehouse, auto_suspend)
- [x] Top expensive queries / repeated queries (`snowflake scan`: query patterns, informational)
- [ ] Result cache misses on repeated queries (needs QUERY_HISTORY result-reuse signal)
- [x] Clustering / materialised views cost vs. use, only when the object name is absent from query text (`snowflake scan`: refresh)
- [x] Storage: fail-safe on high-churn permanent tables (`snowflake scan`: transient_tables)
- [ ] Storage: time travel retention per table (needs TABLES.RETENTION_TIME)
- [x] Cloud services above the 10 % daily adjustment (`snowflake scan`: cloud_services; billable = used + adjustment)
- [ ] Validate on one real account export before quoting numbers from the tool

## GPU / ML (AWS SageMaker, EC2 GPU)
- [ ] Idle notebook instances and endpoints
- [ ] GPU utilisation vs instance size
- [ ] Spot / savings plans coverage
- [ ] Training jobs without checkpoints on on-demand

## Logging / Observability
- [ ] Log volume by source, debug logs in prod
- [ ] High-cardinality custom metrics
- [ ] Retention / indexing tiers

## Storage
- [ ] Lifecycle policies, orphaned snapshots, duplicate datasets
