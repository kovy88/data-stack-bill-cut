-- Save the result as: warehouses.csv
-- Warehouse configuration (size, auto-suspend, cluster counts). Metadata only, no table data.
-- Run both statements together ("Run All") with a role that can see every warehouse
-- (e.g. ACCOUNTADMIN or SYSADMIN) and download the result of the second statement.
SHOW WAREHOUSES;

SELECT * FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()));
