-- Save the result as: table_storage_metrics.csv
-- Bytes per table split into active / time travel / fail-safe. Dropped table versions are
-- kept when they still hold time travel or fail-safe bytes: that is where
-- CREATE OR REPLACE pipelines leave their storage.
SELECT
    table_catalog,
    table_schema,
    table_name,
    id,
    is_transient,
    deleted,
    active_bytes,
    time_travel_bytes,
    failsafe_bytes,
    retained_for_clone_bytes
FROM snowflake.account_usage.table_storage_metrics
WHERE NOT deleted
   OR (time_travel_bytes + failsafe_bytes) > 0
ORDER BY failsafe_bytes DESC;
