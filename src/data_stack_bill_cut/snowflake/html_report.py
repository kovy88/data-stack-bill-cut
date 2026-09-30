"""Client-facing HTML for a scan. One file, no assets, safe to attach or open locally."""

from datetime import date
from html import escape

from data_stack_bill_cut.findings import CONFIDENCE_MEANING, Confidence, totals_by_confidence
from data_stack_bill_cut.snowflake.checks import TIB, ScanResult
from data_stack_bill_cut.snowflake.load import from_seconds
from data_stack_bill_cut.snowflake.report import usd, usd_range


def esc(value: object) -> str:
    return escape("" if value is None else str(value), quote=True)


def _period(result: ScanResult) -> str:
    start = from_seconds(result.inputs.window_start_s).date()
    end = from_seconds(result.inputs.window_end_s).date()
    return f"{start} to {end} ({result.inputs.days:.0f} days)"


def _table(headers: list[str], rows: list[list[str]], numeric: set[int] | None = None) -> str:
    numeric = numeric or set()
    heads = []
    for i, header in enumerate(headers):
        cls = ' class="num"' if i in numeric else ""
        heads.append(f"<th{cls}>{esc(header)}</th>")
    body = []
    for row in rows:
        cells = []
        for i, cell in enumerate(row):
            cls = ' class="num"' if i in numeric else ""
            cells.append(f"<td{cls}>{esc(cell)}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return (
        '<div class="sheet"><table><thead><tr>'
        + "".join(heads)
        + "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table></div>"
    )


def html_table(headers: list[str], rows: list[list[str]], numeric: set[int] | None = None) -> str:
    return _table(headers, rows, numeric)


def html_document(title: str, body: str) -> str:
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{esc(title)}</title>\n"
        f"<style>{_CSS}</style>\n</head>\n<body>\n{body}\n</body>\n</html>\n"
    )


def _apply(result: ScanResult) -> str:
    ready = [f for f in result.findings if f.confidence is Confidence.HIGH and f.fix_sql]
    if not ready:
        return ""
    blocks = [f"<h3>{esc(f.title)}</h3>\n<pre>{esc(f.fix_sql)}</pre>" for f in ready]
    return (
        "<h2>Apply this week</h2>"
        "<p>High-confidence changes only. Each statement is reversible.</p>" + "\n".join(blocks)
    )


def _findings(result: ScanResult) -> str:
    if not result.findings:
        return "<h2>Findings</h2><p>No saving above the reporting threshold was found.</p>"
    rows = [
        [str(i), f.title, usd_range(f.annual_usd_low, f.annual_usd_high), f.confidence.value]
        for i, f in enumerate(result.findings, 1)
    ]
    parts = [
        "<h2>Findings</h2>",
        _table(["#", "Finding", "Saving", "Confidence"], rows, numeric={2}),
    ]
    for i, finding in enumerate(result.findings, 1):
        parts.append(f"<h3>{i}. {esc(finding.title)}</h3>")
        parts.append(
            "<p>"
            f"{esc(usd_range(finding.annual_usd_low, finding.annual_usd_high))} per year, "
            f"{esc(finding.confidence.value)} confidence. "
            f"{esc(finding.resource)}."
            "</p>"
        )
        parts.append(f"<p>{esc(finding.action)}</p>")
        if finding.fix_sql:
            parts.append(f"<pre>{esc(finding.fix_sql)}</pre>")
        if finding.evidence:
            parts.append(
                "<ul>" + "".join(f"<li>{esc(item)}</li>" for item in finding.evidence) + "</ul>"
            )
        if finding.risks:
            parts.append(
                "<p>Risks</p><ul>"
                + "".join(f"<li>{esc(item)}</li>" for item in finding.risks)
                + "</ul>"
            )
    return "\n".join(parts)


def _sensitivity(result: ScanResult) -> str:
    frame = result.sensitivity
    if frame.empty:
        return ""
    targets = sorted(frame["auto_suspend_s"].unique())
    rows = []
    for (warehouse, current), group in frame.groupby(["warehouse", "current"], sort=False):
        by_target = group.set_index("auto_suspend_s")
        cells = [
            f"{usd(by_target.at[t, 'annual_usd'])} ({by_target.at[t, 'resumes_per_day']:.0f}/day)"
            if t in by_target.index
            else "–"
            for t in targets
        ]
        rows.append([warehouse, current, *cells])
    return (
        "<h2>Auto-suspend sensitivity</h2>"
        "<p>Annual saving and resumes per day for each AUTO_SUSPEND value, from the same "
        "model. Fewer resumes mean fewer cold caches.</p>"
        + _table(
            ["Warehouse", "Current", *[f"{t} s" for t in targets]],
            rows,
            numeric=set(range(2, 2 + len(targets))),
        )
    )


def _storage(result: ScanResult) -> str:
    candidates = result.storage_candidates
    if candidates is None or candidates.empty:
        return ""
    rows = [
        [
            f"{row.table_catalog}.{row.table_schema}.{row.table_name}",
            f"{row.active_bytes / TIB:,.2f}",
            f"{row.failsafe_bytes / TIB:,.2f}",
            f"{row.time_travel_bytes / TIB:,.2f}",
            str(row.versions),
        ]
        for row in candidates.head(10).itertuples()
    ]
    return "<h2>High-churn permanent tables</h2>" + _table(
        ["Table", "Live TB", "Fail-safe TB", "Time travel TB", "Versions"],
        rows,
        numeric={1, 2, 3, 4},
    )


def _patterns(result: ScanResult) -> str:
    patterns = result.patterns
    if patterns.empty:
        return ""
    rows = [
        [
            (row.sample or row.pattern)[:70],
            row.warehouse,
            f"{row.runs_per_day:,.0f}",
            f"{row.avg_exec_s:,.1f}",
            f"{row.cache_share:.0%}",
            usd(row.annual_usd),
        ]
        for row in patterns.itertuples()
    ]
    return (
        "<h2>Most expensive query patterns</h2>"
        "<p>Not counted in the saving above. Cost is execution time times the warehouse rate, "
        "with idle time excluded.</p>"
        + _table(
            ["Query (first 70 chars)", "Warehouse", "Runs/day", "Avg s", "Cache", "Annual"],
            rows,
            numeric={2, 3, 4, 5},
        )
    )


def _baseline(result: ScanResult) -> str:
    rows = [
        [
            row.warehouse,
            row.size,
            row.auto_suspend,
            f"{row.credits_per_day:,.1f}",
            f"{row.queries_per_day:,.0f}",
            usd(row.annual_usd),
        ]
        for row in result.baseline.itertuples()
    ]
    return (
        "<h2>Baseline for verification</h2>"
        "<p>After 60–90 days the same exports are compared with this table, in credits per day "
        "and per 1,000 queries.</p>"
        + _table(
            ["Warehouse", "Size", "Auto-suspend", "Credits/day", "Queries/day", "Annual"],
            rows,
            numeric={3, 4, 5},
        )
    )


def _method(result: ScanResult) -> str:
    cfg = result.config
    items = [
        "Source: SNOWFLAKE.ACCOUNT_USAGE and SHOW WAREHOUSES, exported by you. "
        "No table data was read.",
        "A warehouse is billed per second from the first query until AUTO_SUSPEND seconds "
        "after the last one, with a 60-second minimum per resume.",
        "If the model overestimates the metered bill, the saving is scaled down. "
        "It is never scaled up.",
        "Annual figures assume a similar workload. A downsizing range is computed after the "
        "auto-suspend change on the same warehouse.",
        f"Prices: {cfg.credit_price:,.2f} USD per credit and {cfg.storage_price_tb_month:,.2f} "
        "USD per TB-month, as given by you.",
        f"Findings under {usd(cfg.min_annual_usd)} per year are left out.",
        *result.notes,
    ]
    return "<h2>Method</h2><ul>" + "".join(f"<li>{esc(item)}</li>" for item in items) + "</ul>"


_CSS = """
:root {
  --paper: #e7eee9;
  --sheet: #f7faf8;
  --ink: #17211c;
  --muted: #4e5e56;
  --rule: #c9d5ce;
  --apply: #0f5c40;
}
* { box-sizing: border-box; }
html { background: var(--paper); color: var(--ink); }
body {
  margin: 0 auto;
  max-width: 52rem;
  padding: 2.5rem 1.25rem 4rem;
  font-family: "Iowan Old Style", Palatino, "Palatino Linotype", Georgia, serif;
  font-size: 1.05rem;
  line-height: 1.45;
}
h1 { font-size: 1.8rem; font-weight: 600; letter-spacing: -0.02em; margin: 0.2rem 0 0.4rem; }
h2 { font-size: 1.25rem; margin: 2.2rem 0 0.6rem; }
h3 { font-size: 1.05rem; margin: 1.6rem 0 0.3rem; }
p { margin: 0.4rem 0 0.7rem; max-width: 68ch; }
.kicker { color: var(--muted); margin: 0; }
.banner { border-left: 3px solid var(--apply); padding-left: 0.8rem; color: var(--muted); }
.statement { margin: 1.6rem 0 1rem; }
.statement .amount {
  font-size: 3.4rem;
  line-height: 1;
  letter-spacing: -0.03em;
  font-variant-numeric: tabular-nums;
  color: var(--apply);
  margin: 0.15rem 0;
}
.meta { color: var(--muted); }
.sheet { overflow-x: auto; margin: 0.8rem 0 1rem; }
table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
th, td {
  text-align: left;
  padding: 0.45rem 0 0.45rem 0;
  border-bottom: 1px solid var(--rule);
  vertical-align: baseline;
}
th + th, td + td { padding-left: 1.25rem; }
th { font-weight: 600; }
.num {
  text-align: right;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  width: 1%;
}
pre {
  font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  font-size: 0.82rem;
  background: var(--sheet);
  border-left: 3px solid var(--apply);
  padding: 0.7rem 0.9rem;
  overflow-x: auto;
  white-space: pre-wrap;
}
ul { margin: 0.2rem 0 0.8rem; padding-left: 1.1rem; }
li { margin: 0.2rem 0; }
@media print {
  html { background: white; }
  body { padding: 0; max-width: none; }
  pre, .statement .amount { color: black; }
}
"""


def render_html(
    result: ScanResult,
    *,
    client: str = "Snowflake account",
    generated_on: date | None = None,
    fee_share: float = 0.25,
    banner: str | None = None,
) -> str:
    generated_on = generated_on or date.today()
    totals = totals_by_confidence(result.findings)
    ready = totals[Confidence.HIGH][0]
    med_low, med_high = totals[Confidence.MEDIUM]
    low_low, low_high = totals[Confidence.LOW]
    compute = result.annual_compute_usd
    share = f"{ready / compute:.0%} of warehouse compute. " if compute > 0 and ready > 0 else ""
    fee = ""
    if fee_share > 0:
        fee = (
            f"<p>Fee: {fee_share:.0%} of the annual saving that shows up on the Snowflake bill "
            "60–90 days after the changes, invoiced once. No verified saving, no fee.</p>"
        )
    banner_html = f'<p class="banner">{esc(banner)}</p>' if banner else ""
    summary = _table(
        ["", "Annual saving", "What the confidence means"],
        [
            ["Ready to apply", usd(ready), f"high: {CONFIDENCE_MEANING[Confidence.HIGH]}"],
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
        numeric={1},
    )
    body = "\n".join(
        [
            '<p class="kicker">Snowflake cost scan</p>',
            f"<h1>{esc(client)}</h1>",
            f'<p class="meta">Period analysed: {esc(_period(result))}. '
            f"Generated {esc(generated_on.isoformat())}.</p>",
            banner_html,
            '<section class="statement">',
            "<p>Ready to apply</p>",
            f'<p class="amount">{esc(usd(ready))}</p>',
            f"<p>{esc(share)}Warehouse compute today is {esc(usd(compute))} per year, "
            "from metered credits in the period, annualised.</p>",
            "</section>",
            fee,
            summary,
            _apply(result),
            _findings(result),
            _sensitivity(result),
            _storage(result),
            _patterns(result),
            _baseline(result),
            _method(result),
        ]
    )
    return html_document(f"Snowflake cost scan: {client}", body)
