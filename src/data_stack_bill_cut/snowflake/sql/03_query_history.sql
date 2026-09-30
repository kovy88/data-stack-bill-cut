-- Save the result as: query_history.csv
-- One row per query that ran on a warehouse in the same window as the metering export.
-- Timings and bytes only; query text is cut to 120 characters and used just to label
-- repeated query patterns in the report. Replace the query_text_prefix line with
-- NULL AS query_text_prefix to leave query text out entirely.
-- If the download is too large, shorten the window (e.g. 14 days) in this file and in
-- 02_warehouse_metering_history.sql, or export with SnowSQL.
SELECT
    query_id,
    query_parameterized_hash,
    REGEXP_REPLACE(LEFT(query_text, 120), '\\s+', ' ') AS query_text_prefix,
    query_type,
    warehouse_name,
    warehouse_size,
    warehouse_type,
    cluster_number,
    user_name,
    role_name,
    execution_status,
    TO_VARCHAR(CONVERT_TIMEZONE('UTC', start_time), 'YYYY-MM-DD HH24:MI:SS.FF3') AS start_time,
    TO_VARCHAR(CONVERT_TIMEZONE('UTC', end_time), 'YYYY-MM-DD HH24:MI:SS.FF3') AS end_time,
    total_elapsed_time,
    compilation_time,
    queued_provisioning_time,
    queued_repair_time,
    queued_overload_time,
    list_external_files_time,
    execution_time,
    bytes_scanned,
    percentage_scanned_from_cache,
    bytes_spilled_to_local_storage,
    bytes_spilled_to_remote_storage,
    credits_used_cloud_services
FROM snowflake.account_usage.query_history
WHERE start_time >= DATEADD(day, -{{DAYS}}, DATEADD(day, -1, CURRENT_DATE()))
  AND start_time < DATEADD(day, -1, CURRENT_DATE())
  AND warehouse_size IS NOT NULL
ORDER BY start_time;
