-- Save the result as: warehouse_metering_history.csv
-- Hourly credits billed per warehouse for the last {{DAYS}} full days (ending yesterday).
SELECT
    TO_VARCHAR(CONVERT_TIMEZONE('UTC', start_time), 'YYYY-MM-DD HH24:MI:SS') AS start_time,
    TO_VARCHAR(CONVERT_TIMEZONE('UTC', end_time), 'YYYY-MM-DD HH24:MI:SS') AS end_time,
    warehouse_id,
    warehouse_name,
    credits_used,
    credits_used_compute,
    credits_used_cloud_services
FROM snowflake.account_usage.warehouse_metering_history
WHERE start_time >= DATEADD(day, -{{DAYS}}, DATEADD(day, -1, CURRENT_DATE()))
  AND start_time < DATEADD(day, -1, CURRENT_DATE())
ORDER BY start_time;
