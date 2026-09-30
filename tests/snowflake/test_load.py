import numpy as np
import pandas as pd
import pytest
from conftest import hourly_metering, query_row, warehouse_row

from data_stack_bill_cut.snowflake.load import (
    FILES,
    InputError,
    credits_per_hour,
    load_inputs,
    normalize_size,
    smaller_size,
    to_seconds,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("X-Small", "X-Small"),
        ("XSMALL", "X-Small"),
        ("x-small", "X-Small"),
        ("Medium", "Medium"),
        ("2X-Large", "2X-Large"),
        ("XXLARGE", "2X-Large"),
        ("X2LARGE", "2X-Large"),
        ("6X-Large", "6X-Large"),
        ("Adaptive", None),
        (None, None),
        (float("nan"), None),
    ],
)
def test_normalize_size(raw, expected):
    assert normalize_size(raw) == expected


def test_credit_rates_and_sizes():
    assert credits_per_hour("X-Small") == 1
    assert credits_per_hour("Large") == 8
    assert credits_per_hour("Large", "SNOWPARK-OPTIMIZED") == 12
    assert np.isnan(credits_per_hour(None))
    assert smaller_size("Medium") == "Small"
    assert smaller_size("X-Small") is None


def test_timestamps_with_and_without_millis_or_offset():
    seconds = to_seconds(
        pd.Series(["2026-09-01 00:00:00", "2026-09-01 00:00:00.500", "2026-09-01T02:00:00+02:00"])
    )
    np.testing.assert_allclose(seconds - seconds[0], [0, 0.5, 0])


def test_auto_suspend_zero_or_null_means_never(write_export):
    path = write_export(
        warehouses=[
            warehouse_row("A", auto_suspend=600),
            warehouse_row("B", auto_suspend=0),
            warehouse_row("C", auto_suspend=None),
        ],
        metering=hourly_metering("A", 1.0, hours=1),
    )
    wh = load_inputs(path).warehouses.set_index("warehouse_name")
    assert wh.loc["A", "auto_suspend_s"] == 600
    assert np.isinf(wh.loc["B", "auto_suspend_s"])
    assert np.isinf(wh.loc["C", "auto_suspend_s"])


def test_window_and_execution_start(write_export):
    path = write_export(
        warehouses=[warehouse_row("A")],
        metering=hourly_metering("A", 1.0, hours=48),
        queries=[query_row("A", 10, 20, COMPILATION_TIME=2000)],
    )
    inputs = load_inputs(path)
    assert inputs.days == pytest.approx(2.0)
    q = inputs.queries.iloc[0]
    assert q["exec_start_s"] - q["start_s"] == pytest.approx(2.0)
    assert q["rate"] == 2.0


def test_missing_column_is_reported(write_export):
    path = write_export(warehouses=[warehouse_row("A")], metering=hourly_metering("A", 1.0))
    pd.DataFrame({"WAREHOUSE_NAME": ["A"]}).to_csv(path / FILES["queries"], index=False)
    with pytest.raises(InputError, match="missing columns"):
        load_inputs(path)


def test_missing_file_is_reported(tmp_path):
    with pytest.raises(InputError, match="warehouses.csv"):
        load_inputs(tmp_path)


def test_snowsight_bom_timezone_and_full_query_text(tmp_path):
    # A raw ACCOUNT_USAGE download: BOM, offset timestamps, full query text, extra columns.
    (tmp_path / FILES["warehouses"]).write_text(
        "\ufeffname,size,auto_suspend,comment\nETL_WH,Small,600,ignore me\n", encoding="utf-8"
    )
    (tmp_path / FILES["metering"]).write_text(
        "START_TIME,END_TIME,WAREHOUSE_NAME,CREDITS_USED_COMPUTE\n"
        '"2026-09-01 00:00:00.000 -0700","2026-09-01 01:00:00.000 -0700",ETL_WH,2\n',
        encoding="utf-8",
    )
    (tmp_path / FILES["queries"]).write_text(
        "WAREHOUSE_NAME,WAREHOUSE_SIZE,START_TIME,END_TIME,EXECUTION_TIME,QUERY_TEXT,BYTES_WRITTEN\n"
        'ETL_WH,Small,"2026-09-01 07:00:00.000 -0700","2026-09-01 07:00:01.000 -0700",1000,'
        '"select   *\nfrom very_wide",999\n',
        encoding="utf-8",
    )
    inputs = load_inputs(tmp_path)
    assert inputs.warehouses.iloc[0]["warehouse_name"] == "ETL_WH"
    assert inputs.metering.iloc[0]["credits_compute"] == 2
    assert inputs.queries.iloc[0]["text"] == "select * from very_wide"
    assert inputs.notes == []


def test_excel_semicolon_export(tmp_path):
    (tmp_path / FILES["warehouses"]).write_text(
        "name;size;auto_suspend\nETL_WH;Small;600\n", encoding="utf-8"
    )
    (tmp_path / FILES["metering"]).write_text(
        "START_TIME;END_TIME;WAREHOUSE_NAME;CREDITS_USED_COMPUTE\n"
        "01.09.2026 00:00:00;01.09.2026 01:00:00;ETL_WH;1,5\n"
        "not a date;01.09.2026 02:00:00;ETL_WH;9\n",
        encoding="utf-8",
    )
    (tmp_path / FILES["queries"]).write_text(
        "WAREHOUSE_NAME;WAREHOUSE_SIZE;START_TIME;END_TIME;EXECUTION_TIME\n"
        "ETL_WH;Small;01.09.2026 00:10:00;01.09.2026 00:10:05;5000\n",
        encoding="utf-8",
    )
    inputs = load_inputs(tmp_path)
    assert inputs.metering["credits_compute"].tolist() == [1.5]
    assert len(inputs.queries) == 1
    assert "Skipped 1 metering" in inputs.notes[0]
