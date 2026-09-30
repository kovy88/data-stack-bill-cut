from datetime import date

from data_stack_bill_cut.findings import CONFIDENCE_MEANING, Confidence, totals_by_confidence
from data_stack_bill_cut.snowflake.checks import TIB, ScanResult
from data_stack_bill_cut.snowflake.load import from_seconds


def usd(value: float) -> str:
    return f"${value:,.0f}"


def usd_range(low: float, high: float) -> str:
    if round(low) == round(high):
        return usd(low)
    return f"{usd(low)} – {usd(high)}"


def table(headers: list[str], rows: list[list[str]], align: str | None = None) -> str:
    align = align or "l" * len(headers)
    sep = ["---:" if a == "r" else "---" for a in align]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(sep) + " |"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def _period(result: ScanResult) -> str:
    start = from_seconds(result.inputs.window_start_s).date()
    end = from_seconds(result.inputs.window_end_s).date()
    return f"{start} to {end} ({result.inputs.days:.0f} days)"


def _summary(result: ScanResult, fee_share: float) -> list[str]:
    totals = totals_by_confidence(result.findings)
    high = totals[Confidence.HIGH][0]
    med_low, med_high = totals[Confidence.MEDIUM]
    low_low, low_high = totals[Confidence.LOW]
    compute = result.annual_compute_usd
    out = [
        "## Summary",
        "",
        f"Warehouse compute today: **{usd(compute)} per year** "
        "(metered credits in the period, annualised).",
        "",
        table(
            ["", "Annual saving", "Confidence"],
            [
                [
                    "Ready to apply",
                    f"**{usd(high)}**",
                    f"high: {CONFIDENCE_MEANING[Confidence.HIGH]}",
                ],
                [
                    "Needs owner sign-off",
                    usd_range(med_low, med_high),
                    f"medium: {CONFIDENCE_MEANING[Confidence.MEDIUM]}",
                ],
                [
                    "Needs a 1-week test",
                    usd_range(low_low, low_high),
                    f"low: {CONFIDENCE_MEANING[Confidence.LOW]}",
                ],
            ],
            "lrl",
        ),
        "",
    ]
    if compute > 0 and high > 0:
        out.append(
            f"The ready-to-apply items alone cut warehouse compute by **{high / compute:.0%}**."
        )
        out.append("")
    if fee_share > 0:
        out += [
            f"Fee: {fee_share:.0%} of the annual saving that shows up on your Snowflake bill "
            "60–90 days after the changes, invoiced once. If no saving is verified, there is "
            "nothing to pay.",
            "",
        ]
    return out


def _findings(result: ScanResult) -> list[str]:
    if not result.findings:
        return ["## Findings", "", "No saving above the reporting threshold was found.", ""]
    rows = [
        [str(i), f.title, usd_range(f.annual_usd_low, f.annual_usd_high), f.confidence.value]
        for i, f in enumerate(result.findings, 1)
    ]
    out = ["## Findings", "", table(["#", "Finding", "Annual saving", "Confidence"], rows, "llrl")]
    for i, f in enumerate(result.findings, 1):
        out += [
            "",
            f"### {i}. {f.title}",
            "",
            f"- **Saving:** {usd_range(f.annual_usd_low, f.annual_usd_high)} per year "
            f"({f.confidence.value} confidence)",
            f"- **Resource:** {f.resource}",
            f"- **Action:** {f.action}",
        ]
        if f.fix_sql:
            out += ["", "```sql", f.fix_sql, "```"]
        if f.evidence:
            out += ["", "Evidence:", ""] + [f"- {e}" for e in f.evidence]
        if f.risks:
            out += ["", "Risks:", ""] + [f"- {r}" for r in f.risks]
    out.append("")
    return out


def _sensitivity(result: ScanResult) -> list[str]:
    s = result.sensitivity
    if s.empty:
        return []
    targets = sorted(s["auto_suspend_s"].unique())
    rows = []
    for (wh, current), group in s.groupby(["warehouse", "current"], sort=False):
        by_target = group.set_index("auto_suspend_s")
        cells = [
            f"{usd(by_target.at[t, 'annual_usd'])} ({by_target.at[t, 'resumes_per_day']:.0f}/day)"
            if t in by_target.index
            else "–"
            for t in targets
        ]
        rows.append([wh, current, *cells])
    return [
        "## Auto-suspend sensitivity",
        "",
        "Annual saving and resumes per day for each AUTO_SUSPEND value, from the same model. "
        "Fewer resumes mean fewer cold caches; pick per warehouse.",
        "",
        table(
            ["Warehouse", "Current", *[f"{t} s" for t in targets]], rows, "ll" + "r" * len(targets)
        ),
        "",
    ]


def _storage(result: ScanResult) -> list[str]:
    c = result.storage_candidates
    if c is None or c.empty:
        return []
    rows = [
        [
            f"{r.table_catalog}.{r.table_schema}.{r.table_name}",
            f"{r.active_bytes / TIB:,.2f}",
            f"{r.failsafe_bytes / TIB:,.2f}",
            f"{r.time_travel_bytes / TIB:,.2f}",
            str(r.versions),
        ]
        for r in c.head(10).itertuples()
    ]
    return [
        "## High-churn permanent tables",
        "",
        table(
            ["Table", "Live TB", "Fail-safe TB", "Time travel TB", "Versions"],
            rows,
            "lrrrr",
        ),
        "",
    ]


def _patterns(result: ScanResult) -> list[str]:
    p = result.patterns
    if p.empty:
        return []
    rows = [
        [
            f"`{(r.sample or r.pattern)[:70]}`",
            r.warehouse,
            f"{r.runs_per_day:,.0f}",
            f"{r.avg_exec_s:,.1f}",
            f"{r.cache_share:.0%}",
            usd(r.annual_usd),
        ]
        for r in p.itertuples()
    ]
    return [
        "## Most expensive query patterns",
        "",
        "Not counted in the saving above. Cost is execution time × warehouse rate (idle time "
        "excluded). Patterns that run many times a day on unchanged data are candidates for "
        "result reuse, incremental models or a materialised table.",
        "",
        table(
            ["Query (first 70 chars)", "Warehouse", "Runs/day", "Avg s", "Cache", "Annual"],
            rows,
            "llrrrr",
        ),
        "",
    ]


def _baseline(result: ScanResult) -> list[str]:
    b = result.baseline
    rows = [
        [
            r.warehouse,
            r.size,
            r.auto_suspend,
            f"{r.credits_per_day:,.1f}",
            f"{r.queries_per_day:,.0f}",
            usd(r.annual_usd),
        ]
        for r in b.itertuples()
    ]
    return [
        "## Baseline for verification",
        "",
        "After 60–90 days the same exports are re-run and credits per day are compared with "
        "this table, both raw and per 1,000 queries, so workload growth neither hides nor "
        "inflates the saving.",
        "",
        table(
            ["Warehouse", "Size", "Auto-suspend", "Credits/day", "Queries/day", "Annual"],
            rows,
            "lllrrr",
        ),
        "",
    ]


def _method(result: ScanResult) -> list[str]:
    cfg = result.config
    lines = [
        "## Method and assumptions",
        "",
        "- Source: SNOWFLAKE.ACCOUNT_USAGE (WAREHOUSE_METERING_HISTORY, QUERY_HISTORY, "
        "TABLE_STORAGE_METRICS) and SHOW WAREHOUSES, exported by you. No table data was read.",
        "- Billing model: a warehouse is billed per second from the first query until "
        "AUTO_SUSPEND seconds after the last one, with a 60-second minimum per resume. Busy "
        "time comes from query execution intervals (after compilation and queueing).",
        "- The model is checked against metered credits per warehouse. If it overestimates the "
        "bill, savings are scaled down to match; they are never scaled up.",
        "- Annual figures = saving in the period × 365 / period length; they assume a similar "
        "workload. Savings add up: the downsizing range is computed after the auto-suspend "
        "change on the same warehouse.",
        f"- Prices: {cfg.credit_price:,.2f} USD per credit and {cfg.storage_price_tb_month:,.2f} "
        "USD per TB-month (1 TB = 1024⁴ bytes), as given by you. Cloud services, serverless "
        "features and data transfer are not included.",
        f"- Findings under {usd(cfg.min_annual_usd)} per year are left out.",
    ]
    lines += [f"- {n}" for n in result.notes]
    lines.append("")
    return lines


def render_markdown(
    result: ScanResult,
    *,
    client: str = "Snowflake account",
    generated_on: date | None = None,
    fee_share: float = 0.25,
    banner: str | None = None,
) -> str:
    generated_on = generated_on or date.today()
    head = [f"# Snowflake cost scan: {client}", ""]
    if banner:
        head += [f"> {banner}", ""]
    head += [
        f"Period analysed: {_period(result)}. Generated {generated_on.isoformat()}.",
        "",
    ]
    sections = (
        head
        + _summary(result, fee_share)
        + _findings(result)
        + _sensitivity(result)
        + _storage(result)
        + _patterns(result)
        + _baseline(result)
        + _method(result)
    )
    return "\n".join(sections).rstrip() + "\n"
