"""Before/after comparison of metered warehouse credits, used to invoice the success fee."""

from datetime import date

import numpy as np
import pandas as pd

from data_stack_bill_cut.snowflake.html_report import esc, html_document, html_table
from data_stack_bill_cut.snowflake.load import ScanInputs, from_seconds
from data_stack_bill_cut.snowflake.report import table, usd


def workload(inputs: ScanInputs) -> pd.DataFrame:
    credits = inputs.metering.groupby("warehouse_name")["credits_compute"].sum()
    queries = inputs.queries.groupby("warehouse_name").size().astype(float)
    df = pd.DataFrame({"credits": credits, "queries": queries}).fillna(0.0)
    df["credits_per_day"] = df["credits"] / inputs.days
    df["queries_per_day"] = df["queries"] / inputs.days
    return df


def compare(before: ScanInputs, after: ScanInputs, credit_price: float) -> pd.DataFrame:
    b, a = workload(before), workload(after)
    df = b.join(a, lsuffix="_before", rsuffix="_after", how="outer").fillna(0.0)
    df["raw_annual_usd"] = (
        (df["credits_per_day_before"] - df["credits_per_day_after"]) * 365 * credit_price
    )
    has_queries = (df["queries_before"] > 0) & (df["queries_after"] > 0)
    per_1k_before = df["credits_before"] / df["queries_before"].where(has_queries) * 1000
    per_1k_after = df["credits_after"] / df["queries_after"].where(has_queries) * 1000
    df["credits_per_1k_before"] = per_1k_before
    df["credits_per_1k_after"] = per_1k_after
    adjusted = (per_1k_before - per_1k_after) * df["queries_per_day_after"] / 1000
    df["workload_adjusted_annual_usd"] = np.where(
        has_queries, adjusted * 365 * credit_price, df["raw_annual_usd"]
    )
    df.index.name = "warehouse"
    return df.sort_values("raw_annual_usd", ascending=False).reset_index()


def _period(inputs: ScanInputs) -> str:
    start = from_seconds(inputs.window_start_s).date()
    end = from_seconds(inputs.window_end_s).date()
    return f"{start} to {end} ({inputs.days:.0f} days)"


def render_verification(
    comparison: pd.DataFrame,
    before: ScanInputs,
    after: ScanInputs,
    *,
    credit_price: float,
    fee_share: float = 0.25,
    client: str = "Snowflake account",
    generated_on: date | None = None,
) -> str:
    generated_on = generated_on or date.today()
    raw = float(comparison["raw_annual_usd"].sum())
    adjusted = float(comparison["workload_adjusted_annual_usd"].sum())

    def per_1k(value: float) -> str:
        return f"{value:,.2f}" if np.isfinite(value) else "–"

    rows = [
        [
            r.warehouse,
            f"{r.credits_per_day_before:,.1f}",
            f"{r.credits_per_day_after:,.1f}",
            f"{r.queries_per_day_before:,.0f}",
            f"{r.queries_per_day_after:,.0f}",
            per_1k(r.credits_per_1k_before),
            per_1k(r.credits_per_1k_after),
            usd(r.raw_annual_usd),
            usd(r.workload_adjusted_annual_usd),
        ]
        for r in comparison.itertuples()
    ]
    lines = [
        f"# Snowflake saving verification: {client}",
        "",
        f"Before: {_period(before)}. After: {_period(after)}. "
        f"Generated {generated_on.isoformat()}. Price: {credit_price:,.2f} USD per credit.",
        "",
        "## Result",
        "",
        table(
            ["Measure", "Annual saving", f"Fee ({fee_share:.0%})"],
            [
                ["Raw (credits per day)", f"**{usd(raw)}**", usd(max(raw, 0) * fee_share)],
                [
                    "Workload-adjusted (credits per 1,000 queries)",
                    f"**{usd(adjusted)}**",
                    usd(max(adjusted, 0) * fee_share),
                ],
            ],
            "lrr",
        ),
        "",
        "Raw compares credits per day. Workload-adjusted compares credits per 1,000 queries "
        "and prices the difference at the after-period query volume, so growth in usage does "
        "not hide the saving and a drop in usage does not inflate it. The contract states "
        "which measure is invoiced.",
        "",
        "## Per warehouse",
        "",
        table(
            [
                "Warehouse",
                "Credits/day before",
                "after",
                "Queries/day before",
                "after",
                "Credits/1k q before",
                "after",
                "Raw annual",
                "Adjusted annual",
            ],
            rows,
            "lrrrrrrrr",
        ),
        "",
    ]
    return "\n".join(lines)


def render_verification_html(
    comparison: pd.DataFrame,
    before: ScanInputs,
    after: ScanInputs,
    *,
    credit_price: float,
    fee_share: float = 0.25,
    client: str = "Snowflake account",
    generated_on: date | None = None,
) -> str:
    generated_on = generated_on or date.today()
    raw = float(comparison["raw_annual_usd"].sum())
    adjusted = float(comparison["workload_adjusted_annual_usd"].sum())

    def per_1k(value: float) -> str:
        return f"{value:,.2f}" if np.isfinite(value) else "–"

    volume_rows = [
        [
            r.warehouse,
            f"{r.credits_per_day_before:,.1f}",
            f"{r.credits_per_day_after:,.1f}",
            f"{r.queries_per_day_before:,.0f}",
            f"{r.queries_per_day_after:,.0f}",
        ]
        for r in comparison.itertuples()
    ]
    money_rows = [
        [
            r.warehouse,
            per_1k(r.credits_per_1k_before),
            per_1k(r.credits_per_1k_after),
            usd(r.raw_annual_usd),
            usd(r.workload_adjusted_annual_usd),
        ]
        for r in comparison.itertuples()
    ]
    shown = adjusted if adjusted > 0 else 0.0
    body = "\n".join(
        [
            '<p class="kicker">Snowflake saving verification</p>',
            f"<h1>{esc(client)}</h1>",
            f'<p class="meta">Before: {esc(_period(before))}. After: {esc(_period(after))}. '
            f"Generated {esc(generated_on.isoformat())}. "
            f"Price: {credit_price:,.2f} USD per credit.</p>",
            '<section class="statement">',
            "<p>Workload-adjusted annual saving</p>",
            f'<p class="amount">{esc(usd(adjusted))}</p>',
            f"<p>Fee at {fee_share:.0%}: {esc(usd(shown * fee_share))}, invoiced once. "
            f"Raw credits-per-day saving is {esc(usd(raw))} "
            f"(fee {esc(usd(max(raw, 0) * fee_share))}). "
            "The contract states which measure is invoiced.</p>",
            "</section>",
            "<p>Workload-adjusted compares credits per 1,000 queries and prices the difference "
            "at the later query volume, so growth in usage does not hide the saving and a drop "
            "in usage does not inflate it.</p>",
            html_table(
                ["Measure", "Annual saving", f"Fee ({fee_share:.0%})"],
                [
                    ["Raw (credits per day)", usd(raw), usd(max(raw, 0) * fee_share)],
                    [
                        "Workload-adjusted (credits per 1,000 queries)",
                        usd(adjusted),
                        usd(max(adjusted, 0) * fee_share),
                    ],
                ],
                numeric={1, 2},
            ),
            "<h2>Per warehouse</h2>",
            html_table(
                ["Warehouse", "Credits/day before", "after", "Queries/day before", "after"],
                volume_rows,
                numeric={1, 2, 3, 4},
            ),
            html_table(
                ["Warehouse", "Credits/1k queries before", "after", "Raw annual", "Adjusted"],
                money_rows,
                numeric={1, 2, 3, 4},
            ),
        ]
    )
    return html_document(f"Snowflake saving verification: {client}", body)
