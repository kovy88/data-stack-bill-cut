-- Save the result as: automatic_clustering_history.csv
-- Credits spent reclustering each table. Priced only when the table name is absent
-- from the query-history export.
SELECT
    database_name,
    schema_name,
    table_name,
    credits_used,
    TO_VARCHAR(CONVERT_TIMEZONE('UTC', start_time), 'YYYY-MM-DD HH24:MI:SS') AS start_time
FROM snowflake.account_usage.automatic_clustering_history
WHERE start_time >= DATEADD(day, -{{DAYS}}, DATEADD(day, -1, CURRENT_DATE()))
  AND start_time < DATEADD(day, -1, CURRENT_DATE())
  AND credits_used > 0
ORDER BY start_time;
