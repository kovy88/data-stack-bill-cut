-- Save the result as: metering_daily_history.csv
-- Daily cloud-services credits and the adjustment that removes the included 10% of compute.
-- Billable cloud services are credits_used_cloud_services + credits_adjustment_cloud_services
-- (the same sum as dbt-snowflake-monitoring). Warehouse metering alone is the wrong grain.
SELECT
    usage_date,
    service_type,
    credits_used_cloud_services,
    credits_adjustment_cloud_services
FROM snowflake.account_usage.metering_daily_history
WHERE usage_date >= DATEADD(day, -{{DAYS}}, DATEADD(day, -1, CURRENT_DATE()))
  AND usage_date < DATEADD(day, -1, CURRENT_DATE())
  AND service_type = 'WAREHOUSE_METERING'
ORDER BY usage_date;
