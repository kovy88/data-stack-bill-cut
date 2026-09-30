import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from data_stack_bill_cut.findings import Confidence, Finding
from data_stack_bill_cut.snowflake.load import ScanInputs, smaller_size
from data_stack_bill_cut.snowflake.simulate import (
    BillingEstimate,
    BusyPeriods,
    busy_periods,
    estimate_billing,
)

GIB = 1024.0**3
TIB = 1024.0**4
CALIBRATION_OK = (0.8, 1.25)


@dataclass(frozen=True)
class ScanConfig:
    credit_price: float
    storage_price_tb_month: float
    target_auto_suspend_s: int = 60
    sensitivity_auto_suspend_s: tuple[int, ...] = (60, 120, 300, 600)
    min_annual_usd: float = 100.0
    min_failsafe_gib: float = 10.0
    downsize_max_p90_exec_s: float = 10.0
    downsize_max_spill_share: float = 0.01
    downsize_min_queries: int = 200


@dataclass
class WarehouseProfile:
    name: str
    size: str | None
    type: str
    auto_suspend_s: float  # inf = never suspends, nan = not in warehouses.csv
    max_cluster_count: float
    metered_credits: float
    query_count: int
    cluster_busy_credits: float
    periods: BusyPeriods
    current: BillingEstimate | None
    p90_exec_s: float
    spill_share: float

    @property
    def extra_cluster_credits(self) -> float:
        return max(self.cluster_busy_credits - self.periods.busy_credits, 0.0)

    @property
    def modelled_credits(self) -> float:
        if self.current is None:
            return float("nan")
        return self.current.credits + self.extra_cluster_credits

    @property
    def calibration(self) -> float:
        modelled = self.modelled_credits
        if not np.isfinite(modelled) or modelled <= 0 or self.metered_credits <= 0:
            return float("nan")
        return self.metered_credits / modelled

    @property
    def scale(self) -> float:
        """Shrink modelled savings when the model overestimates the bill; never inflate."""
        c = self.calibration
        return min(1.0, c) if np.isfinite(c) else 1.0


@dataclass
class ScanResult:
    inputs: ScanInputs
    config: ScanConfig
    profiles: list[WarehouseProfile]
    findings: list[Finding]
    sensitivity: pd.DataFrame
    patterns: pd.DataFrame
    baseline: pd.DataFrame
    storage_candidates: pd.DataFrame | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def annual_compute_usd(self) -> float:
        credits = float(self.inputs.metering["credits_compute"].sum())
        return credits * self.inputs.annualize * self.config.credit_price


def quote_ident(name: str) -> str:
    if re.fullmatch(r"[A-Z_][A-Z0-9_$]*", name):
        return name
    return '"' + name.replace('"', '""') + '"'


def fmt_suspend(seconds: float) -> str:
    if not np.isfinite(seconds):
        return "never"
    return f"{int(seconds)} s"


def profile_warehouses(inputs: ScanInputs) -> list[WarehouseProfile]:
    config = inputs.warehouses.set_index("warehouse_name")
    metered = inputs.metering.groupby("warehouse_name")["credits_compute"].sum()
    queries = inputs.queries.assign(end_s=np.minimum(inputs.queries["end_s"], inputs.window_end_s))
    by_wh = dict(tuple(queries.groupby("warehouse_name")))
    names = sorted(set(config.index) | set(metered.index) | set(by_wh))

    profiles = []
    for name in names:
        all_q = by_wh.get(name, queries.iloc[0:0])
        q = all_q[np.isfinite(all_q["rate"])]
        cfg = config.loc[name] if name in config.index else None
        auto_suspend = float(cfg["auto_suspend_s"]) if cfg is not None else float("nan")
        seen_sizes = q["size"].dropna().mode()
        size = cfg["size"] if cfg is not None else (seen_sizes.iat[0] if len(seen_sizes) else None)

        periods = busy_periods(q["exec_start_s"], q["end_s"], q["rate"])
        cluster_busy = sum(
            busy_periods(c["exec_start_s"], c["end_s"], c["rate"]).busy_credits
            for _, c in q.groupby("cluster")
        )
        current = (
            estimate_billing(periods, auto_suspend, inputs.window_end_s)
            if len(periods) and not np.isnan(auto_suspend)
            else None
        )
        profiles.append(
            WarehouseProfile(
                name=name,
                size=size,
                type=cfg["type"] if cfg is not None else "STANDARD",
                auto_suspend_s=auto_suspend,
                max_cluster_count=float(cfg["max_cluster_count"]) if cfg is not None else 1.0,
                metered_credits=float(metered.get(name, 0.0)),
                query_count=len(all_q),
                cluster_busy_credits=float(cluster_busy),
                periods=periods,
                current=current,
                p90_exec_s=float(q["execution_s"].quantile(0.9)) if len(q) else float("nan"),
                spill_share=float(q["spilled"].mean()) if len(q) else float("nan"),
            )
        )
    return profiles


def _usd(credits: float, inputs: ScanInputs, cfg: ScanConfig) -> float:
    return credits * inputs.annualize * cfg.credit_price


def check_idle_warehouses(
    profiles: list[WarehouseProfile], inputs: ScanInputs, cfg: ScanConfig
) -> list[Finding]:
    findings = []
    for p in profiles:
        if p.query_count > 0 or p.metered_credits <= 0:
            continue
        usd = _usd(p.metered_credits, inputs, cfg)
        if usd < cfg.min_annual_usd:
            continue
        ident = quote_ident(p.name)
        findings.append(
            Finding(
                check="idle_warehouse",
                title=f"Warehouse {p.name} is billed but ran no queries",
                resource=p.name,
                annual_usd_low=usd,
                annual_usd_high=usd,
                confidence=Confidence.HIGH,
                action="Suspend it and set a short auto-suspend; drop it if nobody claims it.",
                evidence=[
                    f"{p.metered_credits:,.1f} compute credits billed over {inputs.days:.0f} days "
                    "with zero queries in QUERY_HISTORY.",
                    "AUTO_SUSPEND is 0/NULL, so it never suspends on its own."
                    if np.isinf(p.auto_suspend_s)
                    else f"AUTO_SUSPEND is {fmt_suspend(p.auto_suspend_s)}.",
                ],
                risks=["Confirm with the owner that nothing outside the window depends on it."],
                fix_sql=f"ALTER WAREHOUSE {ident} SUSPEND;\n"
                f"ALTER WAREHOUSE {ident} SET AUTO_SUSPEND = {cfg.target_auto_suspend_s};",
            )
        )
    return findings


def _auto_suspend_saving(
    p: WarehouseProfile, target_s: float, inputs: ScanInputs
) -> tuple[float, BillingEstimate] | None:
    if p.current is None or not p.auto_suspend_s > target_s:
        return None
    new = estimate_billing(p.periods, target_s, inputs.window_end_s)
    return (p.current.credits - new.credits) * p.scale, new


def check_auto_suspend(
    profiles: list[WarehouseProfile], inputs: ScanInputs, cfg: ScanConfig
) -> list[Finding]:
    findings = []
    target = cfg.target_auto_suspend_s
    for p in profiles:
        result = _auto_suspend_saving(p, target, inputs)
        if result is None:
            continue
        saved_credits, new = result
        usd = _usd(saved_credits, inputs, cfg)
        if usd < cfg.min_annual_usd:
            continue
        cur = p.current
        calibration = p.calibration
        calibrated = np.isfinite(calibration) and (
            CALIBRATION_OK[0] <= calibration <= CALIBRATION_OK[1]
        )
        resumes_now = cur.resumes / inputs.days
        resumes_new = new.resumes / inputs.days
        removable = 1 - new.credits / cur.credits
        evidence = [
            f"Metered compute: {p.metered_credits:,.1f} credits in {inputs.days:.0f} days; "
            f"the billing model reproduces {p.modelled_credits:,.1f} "
            f"(metered/model = {calibration:.2f}).",
            f"{cur.idle_credits / cur.credits:.0%} of the modelled bill is time with no query "
            f"running. Capping every idle stretch at {target} s removes {removable:.0%} of the "
            "bill.",
            f"Resumes per day: {resumes_now:,.0f} now, {resumes_new:,.0f} at {target} s.",
        ]
        if not calibrated:
            evidence.append(
                "Model and metering differ by more than 25 %, so confidence is lowered; "
                "the saving is scaled down to the metered bill."
            )
        if resumes_new > 1.5 * resumes_now:
            risks = [
                "More resumes, and each one starts with a cold local disk cache, so the first "
                "queries after a pause can be slower. The sensitivity table shows how much of "
                "the saving a longer value keeps.",
            ]
        else:
            risks = [
                "The number of resumes stays about the same; only the idle tail after each "
                "burst of work is cut.",
            ]
        findings.append(
            Finding(
                check="auto_suspend",
                title=f"Lower AUTO_SUSPEND on {p.name} from {fmt_suspend(p.auto_suspend_s)} "
                f"to {target} s",
                resource=p.name,
                annual_usd_low=usd,
                annual_usd_high=usd,
                confidence=Confidence.HIGH if calibrated else Confidence.MEDIUM,
                action=f"Set AUTO_SUSPEND = {target}. One statement, reversible at any time.",
                evidence=evidence,
                risks=risks,
                fix_sql=f"ALTER WAREHOUSE {quote_ident(p.name)} SET AUTO_SUSPEND = {target};",
            )
        )
    return findings


def auto_suspend_sensitivity(
    profiles: list[WarehouseProfile], inputs: ScanInputs, cfg: ScanConfig
) -> pd.DataFrame:
    rows = []
    for p in profiles:
        for target in cfg.sensitivity_auto_suspend_s:
            result = _auto_suspend_saving(p, target, inputs)
            if result is None:
                continue
            saved_credits, new = result
            rows.append(
                {
                    "warehouse": p.name,
                    "current": fmt_suspend(p.auto_suspend_s),
                    "auto_suspend_s": target,
                    "annual_usd": _usd(saved_credits, inputs, cfg),
                    "resumes_per_day": new.resumes / inputs.days,
                }
            )
    return pd.DataFrame(
        rows, columns=["warehouse", "current", "auto_suspend_s", "annual_usd", "resumes_per_day"]
    )


def check_downsize(
    profiles: list[WarehouseProfile], inputs: ScanInputs, cfg: ScanConfig
) -> list[Finding]:
    findings = []
    for p in profiles:
        target_size = smaller_size(p.size)
        if (
            target_size is None
            or p.type != "STANDARD"
            or p.current is None
            or p.query_count < cfg.downsize_min_queries
            or p.spill_share > cfg.downsize_max_spill_share
            or p.p90_exec_s > cfg.downsize_max_p90_exec_s
        ):
            continue
        after_suspend_fix = (
            estimate_billing(p.periods, cfg.target_auto_suspend_s, inputs.window_end_s)
            if p.auto_suspend_s > cfg.target_auto_suspend_s
            else p.current
        )
        idle = (after_suspend_fix.idle_credits + after_suspend_fix.topup_credits) * p.scale
        busy = p.cluster_busy_credits * p.scale
        low = _usd(0.5 * idle, inputs, cfg)
        high = _usd(0.5 * (idle + busy), inputs, cfg)
        if high < cfg.min_annual_usd:
            continue
        findings.append(
            Finding(
                check="downsize",
                title=f"Test {p.name} one size smaller ({p.size} to {target_size})",
                resource=p.name,
                annual_usd_low=low,
                annual_usd_high=high,
                confidence=Confidence.LOW,
                action="Run one week on the smaller size and compare query p90 runtime and "
                "credits against the baseline before counting the saving.",
                evidence=[
                    f"{p.query_count:,} queries, p90 execution time {p.p90_exec_s:.1f} s.",
                    f"{p.spill_share:.1%} of queries spilled to disk (memory is not the limit).",
                    "Lower bound: idle time halves in cost regardless of query speed. "
                    "Upper bound: queries are no slower on the smaller size.",
                ],
                risks=[
                    "Scan-heavy queries can take up to twice as long on half the compute.",
                    "Watch queueing; if queries start to queue, add clusters rather than size.",
                ],
                fix_sql=f"ALTER WAREHOUSE {quote_ident(p.name)} "
                f"SET WAREHOUSE_SIZE = '{target_size.upper()}';",
            )
        )
    return findings


def storage_candidates(storage: pd.DataFrame, cfg: ScanConfig) -> pd.DataFrame:
    key = ["table_catalog", "table_schema", "table_name"]
    live = storage[~storage["deleted"]]
    current = live.groupby(key).agg(
        active_bytes=("active_bytes", "sum"), is_transient=("is_transient", "any")
    )
    history = storage.groupby(key).agg(
        failsafe_bytes=("failsafe_bytes", "sum"),
        time_travel_bytes=("time_travel_bytes", "sum"),
        versions=("table_name", "size"),
    )
    tables = current.join(history, how="inner").reset_index()
    mask = (
        ~tables["is_transient"]
        & (tables["failsafe_bytes"] >= cfg.min_failsafe_gib * GIB)
        & (tables["failsafe_bytes"] > tables["active_bytes"])
    )
    out = tables[mask].copy()
    out["churn"] = out["failsafe_bytes"] / out["active_bytes"].where(out["active_bytes"] > 0)
    return out.sort_values("failsafe_bytes", ascending=False).reset_index(drop=True)


def check_storage(candidates: pd.DataFrame, cfg: ScanConfig) -> list[Finding]:
    if candidates.empty:
        return []
    failsafe_tib = candidates["failsafe_bytes"].sum() / TIB
    time_travel_tib = candidates["time_travel_bytes"].sum() / TIB
    low = failsafe_tib * cfg.storage_price_tb_month * 12
    high = (failsafe_tib + time_travel_tib) * cfg.storage_price_tb_month * 12
    if high < cfg.min_annual_usd:
        return []
    schemas = sorted({f"{r.table_catalog}.{r.table_schema}" for r in candidates.itertuples()})
    return [
        Finding(
            check="transient_tables",
            title=f"Make {len(candidates)} high-churn permanent tables transient",
            resource=", ".join(schemas[:4]) + (" …" if len(schemas) > 4 else ""),
            annual_usd_low=low,
            annual_usd_high=high,
            confidence=Confidence.MEDIUM,
            action="Recreate them as TRANSIENT in the pipeline that builds them "
            "(CREATE TRANSIENT TABLE …, dbt `transient: true`) or move them to a TRANSIENT "
            "schema. Fail-safe bytes disappear 7 days after the switch.",
            evidence=[
                f"{failsafe_tib:,.2f} TB in fail-safe and {time_travel_tib:,.2f} TB in time "
                "travel on tables whose fail-safe is larger than their live data, a sign they "
                "are rebuilt or reloaded often.",
                "Lower bound counts fail-safe only; upper bound also counts time travel "
                "(transient tables with DATA_RETENTION_TIME_IN_DAYS = 0).",
            ],
            risks=[
                "Transient tables have no fail-safe: once time travel expires, Snowflake support "
                "cannot recover overwritten data. Use only for tables rebuildable from source.",
            ],
        )
    ]


def query_patterns(inputs: ScanInputs, cfg: ScanConfig, top: int = 10) -> pd.DataFrame:
    q = inputs.queries
    if q.empty:
        return pd.DataFrame()
    q = q.assign(credits=q["execution_s"] * q["rate"].fillna(0.0) / 3600.0)
    grouped = q.groupby("pattern").agg(
        runs=("pattern", "size"),
        credits=("credits", "sum"),
        avg_exec_s=("execution_s", "mean"),
        cache_share=("cache_share", "mean"),
        warehouse=("warehouse_name", lambda s: ", ".join(sorted(s.unique())[:2])),
        sample=("text", "first"),
    )
    grouped["runs_per_day"] = grouped["runs"] / inputs.days
    grouped["annual_usd"] = grouped["credits"] * inputs.annualize * cfg.credit_price
    return grouped.sort_values("credits", ascending=False).head(top).reset_index()


def baseline(profiles: list[WarehouseProfile], inputs: ScanInputs, cfg: ScanConfig) -> pd.DataFrame:
    rows = [
        {
            "warehouse": p.name,
            "size": p.size or "?",
            "auto_suspend": fmt_suspend(p.auto_suspend_s)
            if not np.isnan(p.auto_suspend_s)
            else "?",
            "credits_per_day": p.metered_credits / inputs.days,
            "queries_per_day": p.query_count / inputs.days,
            "annual_usd": _usd(p.metered_credits, inputs, cfg),
        }
        for p in profiles
    ]
    return pd.DataFrame(rows).sort_values("annual_usd", ascending=False).reset_index(drop=True)


def check_cloud_services(inputs: ScanInputs, cfg: ScanConfig) -> list[Finding]:
    """Billable cloud services are used + adjustment, as in dbt-snowflake-monitoring.

    The adjustment column is what removes the included 10% of compute. Summing it
    with credits used is the amount already on the invoice above that allowance.
    """
    cloud = inputs.cloud
    if cloud is None or cloud.empty:
        return []
    credits = float(cloud["billable"].sum())
    high = _usd(credits, inputs, cfg)
    if high < cfg.min_annual_usd:
        return []
    return [
        Finding(
            check="cloud_services",
            title="Cloud services billed above the daily 10% allowance",
            resource="account",
            annual_usd_low=0.0,
            annual_usd_high=high,
            confidence=Confidence.LOW,
            action="This charge is already net of the included 10% of compute. It does not "
            "move when AUTO_SUSPEND changes. Treat the top of the range as an upper bound "
            "until a change to compilation or metadata calls is measured.",
            evidence=[
                f"{credits:,.1f} billable cloud-services credits in the export "
                "(credits used plus the daily adjustment).",
                "Lower bound is zero: the export shows the charge, not a reversible statement "
                "that removes it.",
            ],
        )
    ]


def _object_mentioned(database: str, schema: str, table: str, texts: pd.Series) -> bool:
    blob = " ".join(texts.fillna("").astype(str)).upper()
    qualified = f"{database}.{schema}.{table}".upper()
    short = f"{schema}.{table}".upper()
    return qualified in blob or short in blob


def check_refresh(inputs: ScanInputs, cfg: ScanConfig) -> tuple[list[Finding], str | None]:
    refresh = inputs.refresh
    if refresh is None or refresh.empty:
        return [], None
    texts = inputs.queries["text"] if "text" in inputs.queries.columns else pd.Series(dtype=str)
    has_text = texts.fillna("").astype(str).str.strip().ne("").any()
    if texts.empty or not has_text:
        return [], (
            "Clustering and materialized-view credits were not priced: query text is empty, "
            "so unused objects cannot be told apart from ones the workload reads."
        )
    grouped = refresh.groupby(
        ["kind", "database_name", "schema_name", "table_name"], as_index=False
    )["credits"].sum()
    findings = []
    for row in grouped.itertuples():
        if _object_mentioned(row.database_name, row.schema_name, row.table_name, texts):
            continue
        usd = _usd(float(row.credits), inputs, cfg)
        if usd < cfg.min_annual_usd:
            continue
        name = ".".join(
            quote_ident(part) for part in (row.database_name, row.schema_name, row.table_name)
        )
        if row.kind == "clustering":
            title = f"Suspend reclustering on {name}"
            action = "Nothing in the exported query text names this table. Confirm, then suspend."
            fix = f"ALTER TABLE {name} SUSPEND RECLUSTER;"
        else:
            title = f"Drop unused materialized view {name}"
            action = "Nothing in the exported query text names this view. Confirm, then drop it."
            fix = f"DROP MATERIALIZED VIEW {name};"
        findings.append(
            Finding(
                check="refresh",
                title=title,
                resource=name,
                annual_usd_low=usd,
                annual_usd_high=usd,
                confidence=Confidence.MEDIUM,
                action=action,
                evidence=[
                    f"{float(row.credits):,.1f} refresh credits in the export, and the object "
                    "name does not appear in query text.",
                ],
                risks=[
                    "Query text is only the first 120 characters, so a real reader can be missed. "
                    "Confirm with the owner before dropping or suspending.",
                ],
                fix_sql=fix,
            )
        )
    return findings, None


_CONFIDENCE_ORDER = {Confidence.HIGH: 0, Confidence.MEDIUM: 1, Confidence.LOW: 2}


def run_scan(inputs: ScanInputs, cfg: ScanConfig) -> ScanResult:
    profiles = profile_warehouses(inputs)
    findings = (
        check_idle_warehouses(profiles, inputs, cfg)
        + check_auto_suspend(profiles, inputs, cfg)
        + check_downsize(profiles, inputs, cfg)
    )
    candidates = None
    if inputs.storage is not None:
        candidates = storage_candidates(inputs.storage, cfg)
        findings += check_storage(candidates, cfg)
    findings += check_cloud_services(inputs, cfg)
    refresh_findings, refresh_note = check_refresh(inputs, cfg)
    findings += refresh_findings
    findings.sort(key=lambda f: (_CONFIDENCE_ORDER[f.confidence], -f.annual_usd_low))

    notes = list(inputs.notes)
    if refresh_note:
        notes.append(refresh_note)
    missing_config = [p.name for p in profiles if np.isnan(p.auto_suspend_s) and p.query_count]
    if missing_config:
        notes.append(
            "Not in warehouses.csv, so auto-suspend could not be checked: "
            + ", ".join(missing_config)
        )
    non_standard = [p.name for p in profiles if p.type not in ("STANDARD", "SNOWPARK-OPTIMIZED")]
    if non_standard:
        notes.append(
            "Non-standard warehouse types (rates taken from metering calibration): "
            + ", ".join(non_standard)
        )

    return ScanResult(
        inputs=inputs,
        config=cfg,
        profiles=profiles,
        findings=findings,
        sensitivity=auto_suspend_sensitivity(profiles, inputs, cfg),
        patterns=query_patterns(inputs, cfg),
        baseline=baseline(profiles, inputs, cfg),
        storage_candidates=candidates,
        notes=notes,
    )
