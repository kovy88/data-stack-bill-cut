import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

FILES = {
    "warehouses": "warehouses.csv",
    "metering": "warehouse_metering_history.csv",
    "queries": "query_history.csv",
    "storage": "table_storage_metrics.csv",
    "cloud": "metering_daily_history.csv",
    "clustering": "automatic_clustering_history.csv",
    "materialized_views": "materialized_view_refresh_history.csv",
}

REQUIRED_COLUMNS = {
    "warehouses": ("name", "size", "auto_suspend"),
    "metering": ("start_time", "warehouse_name", "credits_used_compute"),
    "queries": ("warehouse_name", "warehouse_size", "start_time", "end_time", "execution_time"),
    "storage": (
        "table_catalog",
        "table_schema",
        "table_name",
        "is_transient",
        "active_bytes",
        "time_travel_bytes",
        "failsafe_bytes",
    ),
    "cloud": ("usage_date", "credits_used_cloud_services", "credits_adjustment_cloud_services"),
    "clustering": ("database_name", "schema_name", "table_name", "credits_used"),
    "materialized_views": ("database_name", "schema_name", "table_name", "credits_used"),
}

SIZES = (
    "X-Small",
    "Small",
    "Medium",
    "Large",
    "X-Large",
    "2X-Large",
    "3X-Large",
    "4X-Large",
    "5X-Large",
    "6X-Large",
)
STANDARD_CREDITS_PER_HOUR = {size: float(2**i) for i, size in enumerate(SIZES)}
# Snowpark-optimized sizes bill 1.5x standard (dbt-snowflake-monitoring warehouse_credits_map).
TYPE_MULTIPLIER = {"STANDARD": 1.0, "SNOWPARK-OPTIMIZED": 1.5}

_SIZE_ALIASES = {
    "XSMALL": "X-Small",
    "SMALL": "Small",
    "MEDIUM": "Medium",
    "LARGE": "Large",
    "XLARGE": "X-Large",
    "2XLARGE": "2X-Large",
    "XXLARGE": "2X-Large",
    "X2LARGE": "2X-Large",
    "3XLARGE": "3X-Large",
    "XXXLARGE": "3X-Large",
    "X3LARGE": "3X-Large",
    "4XLARGE": "4X-Large",
    "X4LARGE": "4X-Large",
    "5XLARGE": "5X-Large",
    "X5LARGE": "5X-Large",
    "6XLARGE": "6X-Large",
    "X6LARGE": "6X-Large",
}

_EPOCH = pd.Timestamp("1970-01-01", tz="UTC")


class InputError(ValueError):
    pass


def normalize_size(value: object) -> str | None:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    key = re.sub(r"[^0-9A-Z]", "", str(value).upper())
    return _SIZE_ALIASES.get(key)


def credits_per_hour(size: str | None, warehouse_type: str | None = "STANDARD") -> float:
    if size is None or size not in STANDARD_CREDITS_PER_HOUR:
        return float("nan")
    wh_type = (warehouse_type or "STANDARD").upper()
    return STANDARD_CREDITS_PER_HOUR[size] * TYPE_MULTIPLIER.get(wh_type, 1.0)


def smaller_size(size: str | None) -> str | None:
    if size not in SIZES:
        return None
    i = SIZES.index(size)
    return SIZES[i - 1] if i > 0 else None


@dataclass
class ScanInputs:
    warehouses: pd.DataFrame
    metering: pd.DataFrame
    queries: pd.DataFrame
    storage: pd.DataFrame | None
    window_start_s: float
    window_end_s: float
    notes: list[str] = field(default_factory=list)
    cloud: pd.DataFrame | None = None
    refresh: pd.DataFrame | None = None

    @property
    def days(self) -> float:
        return (self.window_end_s - self.window_start_s) / 86400.0

    @property
    def annualize(self) -> float:
        return 365.0 / self.days


_NULL_TEXT = {"", "null", "none", "nat", "nan"}
# Columns the scan reads. Anything else (full query text beyond the prefix, bytes written, …)
# is dropped at read time so a raw ACCOUNT_USAGE export stays small in memory.
_USED_COLUMNS = {
    "warehouses": {
        "name",
        "type",
        "size",
        "auto_suspend",
        "min_cluster_count",
        "max_cluster_count",
    },
    "metering": {
        "start_time",
        "end_time",
        "warehouse_name",
        "credits_used_compute",
        "credits_used_cloud_services",
    },
    "queries": {
        "warehouse_name",
        "warehouse_size",
        "warehouse_type",
        "cluster_number",
        "start_time",
        "end_time",
        "execution_time",
        "compilation_time",
        "queued_provisioning_time",
        "queued_repair_time",
        "queued_overload_time",
        "list_external_files_time",
        "query_parameterized_hash",
        "query_text_prefix",
        "query_text",
        "bytes_scanned",
        "percentage_scanned_from_cache",
        "bytes_spilled_to_local_storage",
        "bytes_spilled_to_remote_storage",
    },
    "storage": {
        "table_catalog",
        "table_schema",
        "table_name",
        "is_transient",
        "deleted",
        "active_bytes",
        "time_travel_bytes",
        "failsafe_bytes",
        "retained_for_clone_bytes",
    },
    "cloud": {
        "usage_date",
        "service_type",
        "credits_used_cloud_services",
        "credits_adjustment_cloud_services",
    },
    "clustering": {"database_name", "schema_name", "table_name", "credits_used", "start_time"},
    "materialized_views": {
        "database_name",
        "schema_name",
        "table_name",
        "credits_used",
        "start_time",
    },
}
_COLUMN_ALIASES = {"query_text": "query_text_prefix"}


def _column_name(value: object) -> str:
    name = str(value).strip().strip('"').lstrip("\ufeff").lower()
    return re.sub(r"\s+", "_", name)


def _sniff_csv(path: Path) -> tuple[str, str]:
    """Comma, or semicolon with a decimal comma (Excel re-save in a CZ locale)."""
    sample = path.read_bytes()[:8192].decode("utf-8-sig", errors="replace")
    header = sample.splitlines()[0] if sample else ""
    if header.count(";") > header.count(","):
        return ";", ","
    return ",", "."


def to_seconds(values: pd.Series) -> np.ndarray:
    text = values.astype("string").str.strip()
    text = text.mask(text.str.lower().isin(_NULL_TEXT))
    ts = pd.to_datetime(text, utc=True, format="ISO8601", errors="coerce")
    missing = ts.isna() & text.notna()
    if missing.any():
        # Raw ACCOUNT_USAGE timestamps: "2026-09-01 00:00:00.000 -0700"
        ts.loc[missing] = pd.to_datetime(text[missing], utc=True, errors="coerce", format="mixed")
    still = ts.isna() & text.notna()
    if still.any():
        # Excel in a CZ locale rewrites dates as D.M.YYYY.
        euro = text[still].str.replace(
            r"^(\d{1,2})\.(\d{1,2})\.(\d{4})(.*)$", r"\3-\2-\1\4", regex=True
        )
        ts.loc[still] = pd.to_datetime(euro, utc=True, errors="coerce", format="mixed")
    return ((ts - _EPOCH) / pd.Timedelta(seconds=1)).to_numpy(dtype=float)


def from_seconds(seconds: float) -> pd.Timestamp:
    return _EPOCH + pd.Timedelta(seconds=float(seconds))


def _read_csv(directory: Path, kind: str, required: bool) -> pd.DataFrame | None:
    path = directory / FILES[kind]
    if not path.exists():
        if required:
            raise InputError(
                f"missing {path.name} in {directory} (see docs/snowflake-export-guide.md)"
            )
        return None
    sep, decimal = _sniff_csv(path)
    header = pd.read_csv(path, nrows=0, sep=sep, encoding="utf-8-sig")
    wanted = _USED_COLUMNS[kind]
    usecols = [c for c in header.columns if _column_name(c) in wanted]
    if not usecols:
        raise InputError(
            f"{path.name} has no recognised columns (see docs/snowflake-export-guide.md)"
        )
    df = pd.read_csv(
        path, sep=sep, decimal=decimal, encoding="utf-8-sig", usecols=usecols, low_memory=False
    )
    df.columns = [_column_name(c) for c in df.columns]
    for source, target in _COLUMN_ALIASES.items():
        if source in df.columns and target not in df.columns:
            df = df.rename(columns={source: target})
    missing = [c for c in REQUIRED_COLUMNS[kind] if c not in df.columns]
    if missing:
        raise InputError(f"{path.name} is missing columns: {', '.join(missing)}")
    return df


def _num(df: pd.DataFrame, column: str, default: float = 0.0) -> pd.Series:
    if column not in df.columns:
        return pd.Series(default, index=df.index, dtype=float)
    return pd.to_numeric(df[column], errors="coerce").fillna(default).astype(float)


def _flag(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(False, index=df.index)
    return df[column].astype(str).str.strip().str.upper().isin({"YES", "Y", "TRUE", "T", "1"})


def _prepare_warehouses(raw: pd.DataFrame) -> pd.DataFrame:
    auto_suspend = pd.to_numeric(raw["auto_suspend"], errors="coerce")
    # AUTO_SUSPEND of 0 or NULL means the warehouse never suspends on its own.
    auto_suspend = auto_suspend.where(auto_suspend > 0, np.inf)
    wh_type = raw["type"] if "type" in raw.columns else pd.Series("STANDARD", index=raw.index)
    return pd.DataFrame(
        {
            "warehouse_name": raw["name"].astype(str).str.strip(),
            "size": raw["size"].map(normalize_size),
            "type": wh_type.fillna("STANDARD").astype(str).str.upper(),
            "auto_suspend_s": auto_suspend.astype(float),
            "min_cluster_count": _num(raw, "min_cluster_count", 1.0),
            "max_cluster_count": _num(raw, "max_cluster_count", 1.0),
        }
    )


def _prepare_metering(raw: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    start = to_seconds(raw["start_time"])
    end = to_seconds(raw["end_time"]) if "end_time" in raw.columns else start + 3600.0
    df = pd.DataFrame(
        {
            "warehouse_name": raw["warehouse_name"].astype(str).str.strip(),
            "start_s": start,
            "end_s": end,
            "credits_compute": _num(raw, "credits_used_compute"),
            "credits_cloud_services": _num(raw, "credits_used_cloud_services"),
        }
    )
    keep = np.isfinite(df["start_s"]) & np.isfinite(df["end_s"])
    return df[keep].reset_index(drop=True), int((~keep).sum())


def _prepare_queries(raw: pd.DataFrame, warehouses: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    start = to_seconds(raw["start_time"])
    end = to_seconds(raw["end_time"])
    # Execution starts after compilation and queueing (same offset as
    # dbt-snowflake-monitoring cost_per_query).
    offset_ms = sum(
        _num(raw, c)
        for c in (
            "compilation_time",
            "queued_provisioning_time",
            "queued_repair_time",
            "queued_overload_time",
            "list_external_files_time",
        )
    )
    exec_start = np.minimum(start + offset_ms.to_numpy() / 1000.0, end)

    size = raw["warehouse_size"].map(normalize_size)
    wh_type = (
        raw["warehouse_type"].fillna("STANDARD").astype(str).str.upper()
        if "warehouse_type" in raw.columns
        else pd.Series("STANDARD", index=raw.index)
    )
    rate = pd.Series(
        [credits_per_hour(s, t) for s, t in zip(size, wh_type, strict=True)],
        index=raw.index,
        dtype=float,
    )
    names = raw["warehouse_name"].astype(str).str.strip()
    if rate.isna().any() and not warehouses.empty:
        config_rate = {
            r.warehouse_name: credits_per_hour(r.size, r.type) for r in warehouses.itertuples()
        }
        rate = rate.fillna(names.map(config_rate))

    if "query_text_prefix" in raw.columns:
        text = (
            raw["query_text_prefix"]
            .fillna("")
            .astype(str)
            .str.replace(r"\s+", " ", regex=True)
            .str.slice(0, 120)
        )
    else:
        text = pd.Series("", index=raw.index)
    if "query_parameterized_hash" in raw.columns:
        pattern = raw["query_parameterized_hash"].astype("string").fillna(text)
    else:
        pattern = text
    spilled = (
        _num(raw, "bytes_spilled_to_local_storage") + _num(raw, "bytes_spilled_to_remote_storage")
    ) > 0

    df = pd.DataFrame(
        {
            "warehouse_name": names,
            "size": size,
            "rate": rate,
            "cluster": _num(raw, "cluster_number", 1.0).replace(0.0, 1.0),
            "start_s": start,
            "exec_start_s": exec_start,
            "end_s": end,
            "execution_s": _num(raw, "execution_time") / 1000.0,
            "bytes_scanned": _num(raw, "bytes_scanned"),
            "cache_share": _num(raw, "percentage_scanned_from_cache"),
            "spilled": spilled,
            "pattern": pattern.astype(str),
            "text": text,
        }
    )
    keep = np.isfinite(df["start_s"]) & np.isfinite(df["end_s"])
    return df[keep].reset_index(drop=True), int((~keep).sum())


def _prepare_storage(raw: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "table_catalog": raw["table_catalog"].astype(str),
            "table_schema": raw["table_schema"].astype(str),
            "table_name": raw["table_name"].astype(str),
            "is_transient": _flag(raw, "is_transient"),
            "deleted": _flag(raw, "deleted"),
            "active_bytes": _num(raw, "active_bytes"),
            "time_travel_bytes": _num(raw, "time_travel_bytes"),
            "failsafe_bytes": _num(raw, "failsafe_bytes"),
            "retained_for_clone_bytes": _num(raw, "retained_for_clone_bytes"),
        }
    )


def _prepare_cloud(raw: pd.DataFrame) -> pd.DataFrame:
    used = _num(raw, "credits_used_cloud_services")
    adjustment = _num(raw, "credits_adjustment_cloud_services")
    service = (
        raw["service_type"].fillna("WAREHOUSE_METERING").astype(str).str.upper()
        if "service_type" in raw.columns
        else pd.Series("WAREHOUSE_METERING", index=raw.index)
    )
    frame = pd.DataFrame(
        {
            "usage_date": pd.to_datetime(raw["usage_date"], utc=True, errors="coerce"),
            "service_type": service,
            "used": used,
            "adjustment": adjustment,
            "billable": (used + adjustment).clip(lower=0),
        }
    )
    return frame[frame["service_type"].eq("WAREHOUSE_METERING")].reset_index(drop=True)


def _prepare_refresh(raw: pd.DataFrame, kind: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "kind": kind,
            "database_name": raw["database_name"].astype(str),
            "schema_name": raw["schema_name"].astype(str),
            "table_name": raw["table_name"].astype(str),
            "credits": _num(raw, "credits_used"),
        }
    )


def load_inputs(directory: Path, *, require_config: bool = True) -> ScanInputs:
    directory = Path(directory)
    raw_wh = _read_csv(directory, "warehouses", required=require_config)
    raw_metering = _read_csv(directory, "metering", required=True)
    raw_queries = _read_csv(directory, "queries", required=True)
    raw_storage = _read_csv(directory, "storage", required=False)
    raw_cloud = _read_csv(directory, "cloud", required=False)
    raw_clustering = _read_csv(directory, "clustering", required=False)
    raw_views = _read_csv(directory, "materialized_views", required=False)

    warehouses = (
        _prepare_warehouses(raw_wh)
        if raw_wh is not None
        else pd.DataFrame(
            columns=[
                "warehouse_name",
                "size",
                "type",
                "auto_suspend_s",
                "min_cluster_count",
                "max_cluster_count",
            ]
        )
    )
    metering, dropped_metering = _prepare_metering(raw_metering)
    queries, dropped_queries = _prepare_queries(raw_queries, warehouses)
    storage = _prepare_storage(raw_storage) if raw_storage is not None else None
    cloud = _prepare_cloud(raw_cloud) if raw_cloud is not None else None
    refresh_parts = []
    if raw_clustering is not None:
        refresh_parts.append(_prepare_refresh(raw_clustering, "clustering"))
    if raw_views is not None:
        refresh_parts.append(_prepare_refresh(raw_views, "materialized_view"))
    refresh = pd.concat(refresh_parts, ignore_index=True) if refresh_parts else None

    if metering.empty:
        raise InputError("warehouse_metering_history.csv has no usable rows (check the timestamps)")
    notes = []
    if dropped_metering:
        notes.append(
            f"Skipped {dropped_metering} metering rows with a timestamp that could not be parsed."
        )
    if dropped_queries:
        notes.append(
            f"Skipped {dropped_queries} queries with a timestamp that could not be parsed."
        )
    window_start = float(metering["start_s"].min())
    window_end = float(metering["end_s"].max())
    return ScanInputs(
        warehouses, metering, queries, storage, window_start, window_end, notes, cloud, refresh
    )
