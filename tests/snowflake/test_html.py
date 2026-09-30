import pandas as pd
from conftest import hourly_metering, query_row, warehouse_row

from data_stack_bill_cut.snowflake.checks import ScanConfig, run_scan
from data_stack_bill_cut.snowflake.html_report import render_html
from data_stack_bill_cut.snowflake.load import ScanInputs, load_inputs
from data_stack_bill_cut.snowflake.verify import compare, render_verification_html


def test_html_escapes_client_name_and_includes_the_statement(write_export):
    path = write_export(
        warehouses=[warehouse_row("ETL_WH", "Small", 600)],
        metering=hourly_metering("ETL_WH", 35.2 / 24),
        queries=[query_row("ETL_WH", k * 900, k * 900 + 60) for k in range(96)],
    )
    result = run_scan(load_inputs(path), ScanConfig(credit_price=3, storage_price_tb_month=23))
    html = render_html(result, client='Acme <script>alert("x")</script>', banner="note & more")
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html
    assert "note &amp; more" in html
    assert "Ready to apply" in html
    assert "Apply this week" in html
    assert "ALTER WAREHOUSE ETL_WH SET AUTO_SUSPEND = 60;" in html
    assert html.startswith("<!DOCTYPE html>")


def _one_day(credits: float, query_count: int, start: float) -> ScanInputs:
    queries = pd.DataFrame({"warehouse_name": ["WH"] * query_count})
    metering = pd.DataFrame(
        {
            "warehouse_name": ["WH"],
            "start_s": [start],
            "end_s": [start + 86400],
            "credits_compute": [credits],
            "credits_cloud_services": [0.0],
        }
    )
    return ScanInputs(
        warehouses=pd.DataFrame(),
        metering=metering,
        queries=queries,
        storage=None,
        window_start_s=start,
        window_end_s=start + 86400,
    )


def test_verification_html_states_the_fee_and_escapes():
    before = _one_day(10, 100, 0)
    after = _one_day(4, 100, 10_000_000)
    html = render_verification_html(
        compare(before, after, credit_price=3),
        before,
        after,
        credit_price=3,
        client="Acme <b>",
    )
    assert "Acme &lt;b&gt;" in html
    assert "<b>" not in html.split("<body>", 1)[-1]
    assert "Workload-adjusted annual saving" in html
    # 6 credits/day * 365 * $3 = $6,570
    assert "$6,570" in html
