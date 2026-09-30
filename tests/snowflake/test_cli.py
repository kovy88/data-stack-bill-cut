from data_stack_bill_cut.cli import main
from data_stack_bill_cut.snowflake.extract import extraction_queries


def test_extraction_queries_render_window():
    queries = extraction_queries(days=14)
    assert sorted(queries) == [
        "01_warehouses.sql",
        "02_warehouse_metering_history.sql",
        "03_query_history.sql",
        "04_table_storage_metrics.sql",
        "05_metering_daily_history.sql",
        "06_automatic_clustering_history.sql",
        "07_materialized_view_refresh_history.sql",
    ]
    assert "-14" in queries["03_query_history.sql"]
    assert all("{{" not in sql for sql in queries.values())


def test_demo_scan_and_verify(tmp_path):
    before, after = tmp_path / "before", tmp_path / "after"
    assert main(["snowflake", "demo-data", "--out", str(before), "--days", "7"]) == 0
    assert (
        main(
            [
                "snowflake",
                "demo-data",
                "--out",
                str(after),
                "--days",
                "7",
                "--scenario",
                "after",
                "--end",
                "2026-12-27",
            ]
        )
        == 0
    )

    report = tmp_path / "report.md"
    args = ["snowflake", "scan", str(before), "--credit-price", "3", "--storage-price", "23"]
    assert main([*args, "--out", str(report)]) == 0
    text = report.read_text()
    for expected in ("## Summary", "LEGACY_REPORTING_WH", "LOADING_WH", "## Baseline"):
        assert expected in text

    verification = tmp_path / "verify.md"
    verify_args = ["--before", str(before), "--after", str(after), "--credit-price", "3"]
    assert main(["snowflake", "verify", *verify_args, "--out", str(verification)]) == 0
    assert "Workload-adjusted" in verification.read_text()


def test_scan_reports_missing_export(tmp_path, capsys):
    args = ["snowflake", "scan", str(tmp_path), "--credit-price", "3", "--storage-price", "23"]
    assert main(args) == 2
    assert "missing" in capsys.readouterr().err
