from pathlib import Path

import pandas as pd
import pytest

from data_stack_bill_cut.snowflake.load import FILES

DAY_START = pd.Timestamp("2026-09-01", tz="UTC")


def ts(seconds: float, millis: bool = True) -> str:
    value = DAY_START + pd.Timedelta(seconds=seconds)
    fmt = "%Y-%m-%d %H:%M:%S.%f" if millis else "%Y-%m-%d %H:%M:%S"
    text = value.strftime(fmt)
    return text[:-3] if millis else text


def warehouse_row(name, size="Small", auto_suspend=600, **extra):
    return {"name": name, "type": "STANDARD", "size": size, "auto_suspend": auto_suspend, **extra}


def query_row(warehouse, start_s, end_s, size="Small", **extra):
    return {
        "WAREHOUSE_NAME": warehouse,
        "WAREHOUSE_SIZE": size,
        "START_TIME": ts(start_s),
        "END_TIME": ts(end_s),
        "EXECUTION_TIME": int((end_s - start_s) * 1000),
        "QUERY_PARAMETERIZED_HASH": extra.pop("pattern", "h1"),
        **extra,
    }


def hourly_metering(warehouse, credits_per_hour, hours=24):
    return [
        {
            "START_TIME": ts(h * 3600, millis=False),
            "END_TIME": ts((h + 1) * 3600, millis=False),
            "WAREHOUSE_NAME": warehouse,
            "CREDITS_USED_COMPUTE": credits_per_hour[h]
            if isinstance(credits_per_hour, list)
            else credits_per_hour,
        }
        for h in range(hours)
    ]


_EMPTY_COLUMNS = {
    "warehouses": ["name", "type", "size", "auto_suspend"],
    "metering": ["START_TIME", "END_TIME", "WAREHOUSE_NAME", "CREDITS_USED_COMPUTE"],
    "queries": [
        "WAREHOUSE_NAME",
        "WAREHOUSE_SIZE",
        "START_TIME",
        "END_TIME",
        "EXECUTION_TIME",
        "QUERY_PARAMETERIZED_HASH",
    ],
}


@pytest.fixture
def write_export(tmp_path: Path):
    def write(*, warehouses=(), metering=(), queries=(), storage=None) -> Path:
        for kind, rows in (
            ("warehouses", warehouses),
            ("metering", metering),
            ("queries", queries),
        ):
            rows = list(rows)
            df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=_EMPTY_COLUMNS[kind])
            df.to_csv(tmp_path / FILES[kind], index=False)
        if storage is not None:
            pd.DataFrame(storage).to_csv(tmp_path / FILES["storage"], index=False)
        return tmp_path

    return write
