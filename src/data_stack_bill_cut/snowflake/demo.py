"""Synthetic Snowflake account for demos and tests. Not client data.

The account has the waste patterns a scan typically looks for: long auto-suspend on
bursty ETL, a data-science warehouse left up between ad-hoc queries, a forgotten warehouse
that never suspends, short BI queries on a larger size than needed, and permanent staging
tables that are rebuilt every day.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from data_stack_bill_cut.snowflake.load import FILES, credits_per_hour
from data_stack_bill_cut.snowflake.simulate import billed_segments, busy_periods

DEFAULT_END = pd.Timestamp("2026-09-28", tz="UTC")
GIB = 1024**3
HOUR = 3600.0
DAY = 86400.0


@dataclass(frozen=True)
class DemoWarehouse:
    name: str
    size: str
    auto_suspend: int | None
    max_cluster_count: int = 1


BEFORE = (
    DemoWarehouse("LOADING_WH", "Small", 300),
    DemoWarehouse("TRANSFORM_WH", "Large", 300),
    DemoWarehouse("BI_WH", "Medium", 600, max_cluster_count=3),
    DemoWarehouse("DS_WH", "Large", 1800),
    DemoWarehouse("LEGACY_REPORTING_WH", "X-Small", None),
)

AFTER = (
    DemoWarehouse("LOADING_WH", "Small", 60),
    DemoWarehouse("TRANSFORM_WH", "Large", 60),
    DemoWarehouse("BI_WH", "Medium", 120, max_cluster_count=3),
    DemoWarehouse("DS_WH", "Large", 60),
)


def _hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


class _Queries:
    def __init__(self, rng: np.random.Generator):
        self.rng = rng
        self.rows: list[dict] = []

    def add(
        self,
        warehouse: str,
        start: float,
        exec_s: float,
        text: str,
        *,
        cluster: int = 1,
        bytes_scanned: float = 0.0,
        spill: bool = False,
        cache: float = 0.0,
        query_type: str = "SELECT",
        user: str = "SVC_ETL",
        role: str = "TRANSFORMER",
    ) -> float:
        compile_s = self.rng.uniform(0.05, 0.4)
        end = start + compile_s + exec_s
        self.rows.append(
            {
                "warehouse": warehouse,
                "start": start,
                "end": end,
                "compile_ms": compile_s * 1000,
                "exec_ms": exec_s * 1000,
                "text": text,
                "cluster": cluster,
                "bytes_scanned": bytes_scanned,
                "spill_bytes": bytes_scanned * 0.3 if spill else 0.0,
                "cache": cache,
                "query_type": query_type,
                "user": user,
                "role": role,
            }
        )
        return end


def _loading(q: _Queries, start: float, end: float) -> None:
    steps = [
        ("COPY", "COPY INTO RAW.ORDERS FROM @RAW.S3_ORDERS FILE_FORMAT = (TYPE = PARQUET)"),
        ("COPY", "COPY INTO RAW.EVENTS FROM @RAW.S3_EVENTS FILE_FORMAT = (TYPE = JSON)"),
        ("COPY", "COPY INTO RAW.CUSTOMERS FROM @RAW.S3_CRM FILE_FORMAT = (TYPE = CSV)"),
        ("MERGE", "MERGE INTO RAW.ORDERS_CURRENT t USING RAW.ORDERS_STREAM s ON t.ID = s.ID"),
        ("MERGE", "MERGE INTO RAW.CUSTOMERS_CURRENT t USING RAW.CUSTOMERS_STREAM s ON t.ID = s.ID"),
        ("SELECT", "SELECT COUNT(*) FROM RAW.EVENTS WHERE _LOADED_AT > ?"),
    ]
    slot = start
    while slot < end:
        t = slot + 120 + q.rng.normal(0, 20)
        for query_type, text in steps:
            exec_s = q.rng.lognormal(np.log(7), 0.45)
            t = q.add("LOADING_WH", t, exec_s, text, query_type=query_type, bytes_scanned=2e8)
            t += q.rng.uniform(0.2, 1.0)
        slot += 15 * 60


def _transform(q: _Queries, start: float, end: float) -> None:
    n_models = 70
    # Fixed seed: the dbt project is the same in every scenario, only run-to-run noise varies.
    medians = np.random.default_rng(0).lognormal(np.log(7), 0.8, n_models)
    heavy = {3, 17}
    medians[list(heavy)] = [95, 70]
    run = start + 5 * 60
    while run < end:
        full_refresh = pd.Timestamp(run, unit="s").hour == 2
        t = run
        for i, median in enumerate(medians):
            exec_s = median * q.rng.lognormal(0, 0.2) * (3 if full_refresh else 1)
            text = f"create or replace transient table ANALYTICS.MARTS.MODEL_{i:02d} as (select …"
            t = q.add(
                "TRANSFORM_WH",
                t,
                exec_s,
                text,
                query_type="CREATE_TABLE_AS_SELECT",
                user="SVC_DBT",
                bytes_scanned=5e9 * median / 7,
                spill=i in heavy,
            )
            t += q.rng.uniform(1, 3)
        run += HOUR


_DASHBOARDS = [
    "SELECT DATE_TRUNC('day', ORDER_TS) d, SUM(REVENUE) FROM MARTS.FCT_REVENUE WHERE …",
    "SELECT REGION, COUNT(DISTINCT CUSTOMER_ID) FROM MARTS.DIM_CUSTOMER GROUP BY 1",
    "SELECT * FROM MARTS.KPI_DAILY WHERE DAY >= DATEADD(day, -30, CURRENT_DATE())",
    "SELECT CHANNEL, SUM(SPEND) / NULLIF(SUM(ORDERS), 0) FROM MARTS.MARKETING_CAC …",
    "SELECT PRODUCT, SUM(QTY) FROM MARTS.FCT_ORDER_LINES WHERE ORDER_DATE = ? GROUP BY 1",
    "SELECT COHORT, MONTH_N, RETENTION FROM MARTS.RETENTION_COHORTS ORDER BY 1, 2",
    "SELECT COUNT(*) FROM MARTS.FCT_SESSIONS WHERE SESSION_START >= ?",
    "SELECT STATUS, COUNT(*) FROM MARTS.FCT_TICKETS GROUP BY 1",
]


def _bi(q: _Queries, start: float, end: float, volume: float = 1.0) -> None:
    weights = 1 / np.arange(1, len(_DASHBOARDS) + 1)
    weights /= weights.sum()

    def query(t: float, cluster: int = 1) -> None:
        text = _DASHBOARDS[q.rng.choice(len(_DASHBOARDS), p=weights)]
        q.add(
            "BI_WH",
            t,
            q.rng.lognormal(np.log(1.0), 0.7),
            text,
            cluster=cluster,
            bytes_scanned=q.rng.lognormal(np.log(5e7), 1.0),
            cache=q.rng.uniform(0.6, 0.95),
            user="SVC_LOOKER",
            role="REPORTER",
        )

    t = start
    while t < end:
        ts = pd.Timestamp(t, unit="s")
        weekday = ts.dayofweek < 5
        if weekday and 7 <= ts.hour < 17:
            mean_gap = 20.0 / volume
        elif weekday:
            mean_gap = 40 * 60.0 / volume
        else:
            mean_gap = 90 * 60.0 / volume
        t += q.rng.exponential(mean_gap)
        if t >= end:
            break
        peak = weekday and 9 <= ts.hour < 11
        query(t, cluster=2 if peak and q.rng.random() < 0.2 else 1)


def _data_science(q: _Queries, start: float, end: float) -> None:
    texts = [
        "SELECT * FROM ANALYTICS.FEATURES.CUSTOMER_FEATURES SAMPLE (10) WHERE …",
        "SELECT USER_ID, ARRAY_AGG(EVENT) FROM RAW.EVENTS WHERE EVENT_DATE >= ? GROUP BY 1",
        "CREATE OR REPLACE TABLE SANDBOX.DS.CHURN_TRAINING AS SELECT …",
        "SELECT APPROX_PERCENTILE(BASKET_VALUE, 0.9) FROM MARTS.FCT_ORDERS WHERE …",
    ]
    day = start
    while day < end:
        if pd.Timestamp(day, unit="s").dayofweek < 5:
            for session_start in np.sort(q.rng.uniform(8 * HOUR, 16 * HOUR, 3)):
                t = day + session_start
                for _ in range(q.rng.integers(4, 11)):
                    text = texts[q.rng.integers(len(texts))]
                    t = q.add(
                        "DS_WH",
                        t,
                        q.rng.lognormal(np.log(45), 0.9),
                        text,
                        user="ANALYST_DS",
                        role="DATA_SCIENTIST",
                        bytes_scanned=q.rng.lognormal(np.log(2e10), 1.0),
                        spill=q.rng.random() < 0.1,
                    )
                    t += q.rng.uniform(60, 600)
        day += DAY


def _hourly_credits(
    starts: np.ndarray, ends: np.ndarray, rates: np.ndarray, window_start: float, n_hours: int
) -> np.ndarray:
    out = np.zeros(n_hours)
    window_end = window_start + n_hours * HOUR
    for s, e, r in zip(starts, ends, rates, strict=True):
        s, e = max(s, window_start), min(e, window_end)
        while s < e:
            h = int((s - window_start) // HOUR)
            chunk_end = min(e, window_start + (h + 1) * HOUR)
            out[h] += (chunk_end - s) * r / HOUR
            s = chunk_end
    return out


def _timestamps(seconds: np.ndarray, millis: bool) -> pd.Series:
    ts = pd.Series(pd.to_datetime(seconds, unit="s", utc=True))
    if millis:
        return ts.dt.strftime("%Y-%m-%d %H:%M:%S.%f").str[:-3]
    return ts.dt.strftime("%Y-%m-%d %H:%M:%S")


def _metering(
    queries: pd.DataFrame,
    warehouses: tuple[DemoWarehouse, ...],
    window_start: float,
    days: int,
    rng: np.random.Generator,
) -> pd.DataFrame:
    n_hours = days * 24
    window_end = window_start + n_hours * HOUR
    frames = []
    for wh in warehouses:
        rate = credits_per_hour(wh.size)
        q = queries[queries["warehouse"] == wh.name]
        if q.empty:
            hourly = np.full(n_hours, rate)
        else:
            exec_start = (q["start"] + q["compile_ms"] / 1000).to_numpy()
            end = q["end"].to_numpy()
            periods = busy_periods(exec_start, end, np.full(len(q), rate))
            seg = billed_segments(periods, wh.auto_suspend, window_end)
            hourly = _hourly_credits(*seg, window_start, n_hours)
            extra = q["cluster"].to_numpy() > 1
            if extra.any():
                extra_periods = busy_periods(
                    exec_start[extra], end[extra], np.full(extra.sum(), rate)
                )
                hourly += _hourly_credits(
                    extra_periods.start,
                    extra_periods.end + 120,
                    extra_periods.rate,
                    window_start,
                    n_hours,
                )
            hourly *= rng.uniform(1.0, 1.06, n_hours)
        starts = window_start + np.arange(n_hours) * HOUR
        keep = hourly > 0
        cloud = hourly * rng.uniform(0.02, 0.06, n_hours)
        frames.append(
            pd.DataFrame(
                {
                    "START_TIME": _timestamps(starts[keep], millis=False),
                    "END_TIME": _timestamps(starts[keep] + HOUR, millis=False),
                    "WAREHOUSE_ID": int(_hash(wh.name)[:4], 16),
                    "WAREHOUSE_NAME": wh.name,
                    "CREDITS_USED": np.round(hourly[keep] + cloud[keep], 9),
                    "CREDITS_USED_COMPUTE": np.round(hourly[keep], 9),
                    "CREDITS_USED_CLOUD_SERVICES": np.round(cloud[keep], 9),
                }
            )
        )
    return pd.concat(frames).sort_values("START_TIME").reset_index(drop=True)


def _query_history(queries: pd.DataFrame, warehouses: tuple[DemoWarehouse, ...]) -> pd.DataFrame:
    sizes = {wh.name: wh.size for wh in warehouses}
    q = queries.sort_values("start").reset_index(drop=True)
    return pd.DataFrame(
        {
            "QUERY_ID": [f"01be{i:012x}" for i in range(len(q))],
            "QUERY_PARAMETERIZED_HASH": q["text"].map(_hash),
            "QUERY_TEXT_PREFIX": q["text"].str.slice(0, 120),
            "QUERY_TYPE": q["query_type"],
            "WAREHOUSE_NAME": q["warehouse"],
            "WAREHOUSE_SIZE": q["warehouse"].map(sizes),
            "WAREHOUSE_TYPE": "STANDARD",
            "CLUSTER_NUMBER": q["cluster"],
            "USER_NAME": q["user"],
            "ROLE_NAME": q["role"],
            "EXECUTION_STATUS": "SUCCESS",
            "START_TIME": _timestamps(q["start"].to_numpy(), millis=True),
            "END_TIME": _timestamps(q["end"].to_numpy(), millis=True),
            "TOTAL_ELAPSED_TIME": ((q["end"] - q["start"]) * 1000).round().astype(int),
            "COMPILATION_TIME": q["compile_ms"].round().astype(int),
            "QUEUED_PROVISIONING_TIME": 0,
            "QUEUED_REPAIR_TIME": 0,
            "QUEUED_OVERLOAD_TIME": 0,
            "LIST_EXTERNAL_FILES_TIME": 0,
            "EXECUTION_TIME": q["exec_ms"].round().astype(int),
            "BYTES_SCANNED": q["bytes_scanned"].round().astype("int64"),
            "PERCENTAGE_SCANNED_FROM_CACHE": q["cache"].round(3),
            "BYTES_SPILLED_TO_LOCAL_STORAGE": q["spill_bytes"].round().astype("int64"),
            "BYTES_SPILLED_TO_REMOTE_STORAGE": 0,
            "CREDITS_USED_CLOUD_SERVICES": 0.00001,
        }
    )


def _warehouses_csv(warehouses: tuple[DemoWarehouse, ...]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "name": [wh.name for wh in warehouses],
            "state": "SUSPENDED",
            "type": "STANDARD",
            "size": [wh.size for wh in warehouses],
            "min_cluster_count": 1,
            "max_cluster_count": [wh.max_cluster_count for wh in warehouses],
            "auto_suspend": [wh.auto_suspend for wh in warehouses],
            "auto_resume": "true",
            "scaling_policy": "STANDARD",
            "owner": "SYSADMIN",
        }
    )


def _storage(rng: np.random.Generator) -> pd.DataFrame:
    rows = []

    def add(db, schema, table, *, transient=False, deleted=False, active=0, tt=0, fs=0):
        rows.append(
            {
                "TABLE_CATALOG": db,
                "TABLE_SCHEMA": schema,
                "TABLE_NAME": table,
                "ID": len(rows) + 1000,
                "IS_TRANSIENT": "YES" if transient else "NO",
                "DELETED": deleted,
                "ACTIVE_BYTES": int(active * GIB),
                "TIME_TRAVEL_BYTES": int(tt * GIB),
                "FAILSAFE_BYTES": int(fs * GIB),
                "RETAINED_FOR_CLONE_BYTES": 0,
            }
        )

    # Rebuilt daily with CREATE OR REPLACE: each dropped version sits in fail-safe for 7 days.
    add("ANALYTICS", "STAGING", "STG_EVENTS", active=410)
    add("ANALYTICS", "STAGING", "STG_EVENTS", deleted=True, tt=405)
    for _ in range(7):
        add("ANALYTICS", "STAGING", "STG_EVENTS", deleted=True, fs=400 * rng.uniform(0.95, 1.05))
    # Truncate + reload every night.
    add("ANALYTICS", "STAGING", "STG_ORDERS", active=120, tt=120, fs=840)
    add("ANALYTICS", "STAGING", "STG_SESSIONS", active=60, tt=55, fs=380)
    add("SANDBOX", "DS", "CHURN_TRAINING", active=12, tt=12, fs=70)
    # Healthy tables for contrast.
    add("RAW", "PUBLIC", "EVENTS", active=5200, tt=50, fs=150)
    add("ANALYTICS", "MARTS", "FCT_REVENUE", active=900, tt=20, fs=35)
    add("ANALYTICS", "MARTS", "DIM_CUSTOMER", active=40, tt=2, fs=5)
    add("ANALYTICS", "SCRATCH", "TMP_FEATURES", transient=True, active=200, tt=200)
    return pd.DataFrame(rows)


def generate(
    out_dir: Path,
    *,
    days: int = 30,
    end: pd.Timestamp = DEFAULT_END,
    scenario: str = "before",
    seed: int = 7,
) -> Path:
    if scenario not in ("before", "after"):
        raise ValueError("scenario must be 'before' or 'after'")
    rng = np.random.default_rng(seed)
    warehouses = BEFORE if scenario == "before" else AFTER
    window_start = float((end - pd.Timedelta(days=days)).timestamp())
    window_end = float(end.timestamp())

    q = _Queries(rng)
    _loading(q, window_start, window_end)
    _transform(q, window_start, window_end)
    _bi(q, window_start, window_end, volume=1.0 if scenario == "before" else 1.1)
    _data_science(q, window_start, window_end)
    queries = pd.DataFrame(q.rows)
    queries = queries[queries["end"] < window_end]

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    _warehouses_csv(warehouses).to_csv(out_dir / FILES["warehouses"], index=False)
    _metering(queries, warehouses, window_start, days, rng).to_csv(
        out_dir / FILES["metering"], index=False
    )
    _query_history(queries, warehouses).to_csv(out_dir / FILES["queries"], index=False)
    _storage(rng).to_csv(out_dir / FILES["storage"], index=False)
    _cloud_csv(end, days).to_csv(out_dir / FILES["cloud"], index=False)
    clustering, views = _refresh_csvs()
    clustering.to_csv(out_dir / FILES["clustering"], index=False)
    views.to_csv(out_dir / FILES["materialized_views"], index=False)
    return out_dir


def _cloud_csv(end: pd.Timestamp, days: int) -> pd.DataFrame:
    # 5 used and -4 adjustment = 1 billable credit per day (dbt-snowflake-monitoring sum).
    dates = pd.date_range(end.normalize() - pd.Timedelta(days=days), periods=days, freq="D")
    return pd.DataFrame(
        {
            "USAGE_DATE": dates.strftime("%Y-%m-%d"),
            "SERVICE_TYPE": "WAREHOUSE_METERING",
            "CREDITS_USED_CLOUD_SERVICES": 5.0,
            "CREDITS_ADJUSTMENT_CLOUD_SERVICES": -4.0,
        }
    )


def _refresh_csvs() -> tuple[pd.DataFrame, pd.DataFrame]:
    # KPI_DAILY is named in the BI query text, so it must not be priced.
    # STALE_CLUSTERED_ORDERS is not.
    clustering = pd.DataFrame(
        {
            "DATABASE_NAME": ["ANALYTICS", "ANALYTICS"],
            "SCHEMA_NAME": ["MARTS", "MARTS"],
            "TABLE_NAME": ["STALE_CLUSTERED_ORDERS", "KPI_DAILY"],
            "CREDITS_USED": [20.0, 20.0],
        }
    )
    views = pd.DataFrame(
        {
            "DATABASE_NAME": ["ANALYTICS"],
            "SCHEMA_NAME": ["MARTS"],
            "TABLE_NAME": ["KPI_DAILY"],
            "CREDITS_USED": [15.0],
        }
    )
    return clustering, views
