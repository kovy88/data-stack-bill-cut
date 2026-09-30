import pandas as pd
import pytest
from conftest import hourly_metering, query_row, warehouse_row

from data_stack_bill_cut.findings import Confidence
from data_stack_bill_cut.snowflake.checks import GIB, TIB, ScanConfig, run_scan
from data_stack_bill_cut.snowflake.load import load_inputs

CFG = ScanConfig(credit_price=1.0, storage_price_tb_month=20.0, min_annual_usd=0.0)


def etl_every_15_minutes(warehouse="ETL_WH"):
    # 96 one-minute jobs per day, 840 s apart: each one leaves a full auto-suspend tail.
    return [query_row(warehouse, k * 900, k * 900 + 60) for k in range(96)]


def by_check(result, check):
    return [f for f in result.findings if f.check == check]


def test_auto_suspend_saving_matches_hand_calculation(write_export):
    # Small = 2 credits/h. Billed now: 96 x (60 + 600) s = 35.2 credits; at 60 s: 6.4 credits.
    path = write_export(
        warehouses=[warehouse_row("ETL_WH", "Small", 600)],
        metering=hourly_metering("ETL_WH", 35.2 / 24),
        queries=etl_every_15_minutes(),
    )
    result = run_scan(load_inputs(path), CFG)
    [finding] = by_check(result, "auto_suspend")
    assert finding.confidence is Confidence.HIGH
    assert finding.annual_usd_low == pytest.approx(28.8 * 365, rel=1e-6)
    assert "AUTO_SUSPEND = 60" in finding.fix_sql


def test_saving_is_scaled_down_when_model_overestimates_the_bill(write_export):
    path = write_export(
        warehouses=[warehouse_row("ETL_WH", "Small", 600)],
        metering=hourly_metering("ETL_WH", 17.6 / 24),
        queries=etl_every_15_minutes(),
    )
    [finding] = by_check(run_scan(load_inputs(path), CFG), "auto_suspend")
    assert finding.confidence is Confidence.MEDIUM
    assert finding.annual_usd_low == pytest.approx(0.5 * 28.8 * 365, rel=1e-6)


def test_no_finding_when_auto_suspend_already_at_target(write_export):
    path = write_export(
        warehouses=[warehouse_row("ETL_WH", "Small", 60)],
        metering=hourly_metering("ETL_WH", 6.4 / 24),
        queries=etl_every_15_minutes(),
    )
    assert by_check(run_scan(load_inputs(path), CFG), "auto_suspend") == []


def test_idle_warehouse_costs_its_whole_bill(write_export):
    path = write_export(
        warehouses=[warehouse_row("OLD_WH", "X-Small", None)],
        metering=hourly_metering("OLD_WH", 1.0),
    )
    [finding] = by_check(run_scan(load_inputs(path), CFG), "idle_warehouse")
    assert finding.annual_usd_low == pytest.approx(24 * 365)
    assert "SUSPEND" in finding.fix_sql


def bi_queries(spill_every=None):
    rows = []
    for k in range(300):
        extra = {}
        if spill_every and k % spill_every == 0:
            extra["BYTES_SPILLED_TO_LOCAL_STORAGE"] = 1_000_000
        rows.append(query_row("BI_WH", k * 30, k * 30 + 1, size="Medium", **extra))
    return rows


def test_downsize_range_for_short_queries(write_export):
    path = write_export(
        warehouses=[warehouse_row("BI_WH", "Medium", 60)],
        metering=hourly_metering("BI_WH", 4.0),
        queries=bi_queries(),
    )
    [finding] = by_check(run_scan(load_inputs(path), CFG), "downsize")
    assert finding.confidence is Confidence.LOW
    assert 0 < finding.annual_usd_low < finding.annual_usd_high
    assert "'SMALL'" in finding.fix_sql


def test_no_downsize_when_queries_spill(write_export):
    path = write_export(
        warehouses=[warehouse_row("BI_WH", "Medium", 60)],
        metering=hourly_metering("BI_WH", 4.0),
        queries=bi_queries(spill_every=10),
    )
    assert by_check(run_scan(load_inputs(path), CFG), "downsize") == []


def storage_row(table, *, transient="NO", deleted=False, active=0, tt=0, fs=0, schema="STAGING"):
    return {
        "TABLE_CATALOG": "DB",
        "TABLE_SCHEMA": schema,
        "TABLE_NAME": table,
        "IS_TRANSIENT": transient,
        "DELETED": deleted,
        "ACTIVE_BYTES": active * GIB,
        "TIME_TRAVEL_BYTES": tt * GIB,
        "FAILSAFE_BYTES": fs * GIB,
    }


def test_cloud_services_billable_is_used_plus_adjustment(write_export):
    path = write_export(
        warehouses=[warehouse_row("ETL_WH", "Small", 60)],
        metering=hourly_metering("ETL_WH", 1.0),
        queries=[query_row("ETL_WH", 10, 20)],
    )
    # 2 billable credits per day for 1 day of metering (hourly fixture is 24 hours).
    pd.DataFrame(
        {
            "USAGE_DATE": ["2026-09-01"],
            "SERVICE_TYPE": ["WAREHOUSE_METERING"],
            "CREDITS_USED_CLOUD_SERVICES": [10],
            "CREDITS_ADJUSTMENT_CLOUD_SERVICES": [-8],
        }
    ).to_csv(path / "metering_daily_history.csv", index=False)
    [finding] = by_check(run_scan(load_inputs(path), CFG), "cloud_services")
    assert finding.confidence is Confidence.LOW
    assert finding.annual_usd_low == 0
    # 2 credits * 365 * $1
    assert finding.annual_usd_high == pytest.approx(2 * 365)


def test_unused_refresh_is_priced_and_a_mentioned_view_is_not(write_export):
    path = write_export(
        warehouses=[warehouse_row("ETL_WH", "Small", 60)],
        metering=hourly_metering("ETL_WH", 1.0),
        queries=[query_row("ETL_WH", 10, 70, QUERY_TEXT_PREFIX="select * from MARTS.KPI_DAILY")],
    )
    pd.DataFrame(
        {
            "DATABASE_NAME": ["DB", "DB"],
            "SCHEMA_NAME": ["MARTS", "MARTS"],
            "TABLE_NAME": ["STALE_ORDERS", "KPI_DAILY"],
            "CREDITS_USED": [10, 10],
        }
    ).to_csv(path / "automatic_clustering_history.csv", index=False)
    pd.DataFrame(
        {
            "DATABASE_NAME": ["DB"],
            "SCHEMA_NAME": ["MARTS"],
            "TABLE_NAME": ["KPI_DAILY"],
            "CREDITS_USED": [10],
        }
    ).to_csv(path / "materialized_view_refresh_history.csv", index=False)
    findings = by_check(run_scan(load_inputs(path), CFG), "refresh")
    assert [f.resource for f in findings] == ["DB.MARTS.STALE_ORDERS"]
    assert "SUSPEND RECLUSTER" in findings[0].fix_sql


def test_refresh_without_query_text_is_not_priced(write_export):
    path = write_export(
        warehouses=[warehouse_row("ETL_WH")],
        metering=hourly_metering("ETL_WH", 1.0),
        queries=[query_row("ETL_WH", 10, 20)],
    )
    pd.DataFrame(
        {
            "DATABASE_NAME": ["DB"],
            "SCHEMA_NAME": ["MARTS"],
            "TABLE_NAME": ["STALE_ORDERS"],
            "CREDITS_USED": [10],
        }
    ).to_csv(path / "automatic_clustering_history.csv", index=False)
    result = run_scan(load_inputs(path), CFG)
    assert by_check(result, "refresh") == []
    assert any("query text is empty" in note for note in result.notes)


def test_high_churn_permanent_tables_are_flagged(write_export):
    storage = [
        storage_row("STG", active=100),
        *[storage_row("STG", deleted=True, fs=100) for _ in range(3)],
        storage_row("TMP", transient="YES", active=10, tt=50, fs=0),
        storage_row("FACT", active=1000, fs=50, schema="MARTS"),
        storage_row("GONE", deleted=True, fs=500),
    ]
    path = write_export(
        warehouses=[warehouse_row("ETL_WH")],
        metering=hourly_metering("ETL_WH", 0.0),
        storage=storage,
    )
    result = run_scan(load_inputs(path), CFG)
    assert result.storage_candidates["table_name"].tolist() == ["STG"]
    [finding] = by_check(result, "transient_tables")
    assert finding.annual_usd_low == pytest.approx(300 * GIB / TIB * 20 * 12)
