import argparse
import sys
from pathlib import Path

import pandas as pd

from data_stack_bill_cut.snowflake import demo
from data_stack_bill_cut.snowflake.checks import ScanConfig, run_scan
from data_stack_bill_cut.snowflake.extract import write_extraction_queries
from data_stack_bill_cut.snowflake.html_report import render_html
from data_stack_bill_cut.snowflake.load import InputError, load_inputs
from data_stack_bill_cut.snowflake.report import render_markdown
from data_stack_bill_cut.snowflake.verify import (
    compare,
    render_verification,
    render_verification_html,
)


def _emit(text: str, out: Path | None) -> None:
    if out is None:
        sys.stdout.write(text)
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out}", file=sys.stderr)


def _positive(value: str) -> float:
    number = float(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be > 0")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="data-stack-bill-cut",
        description="Read-only cost scans for data/ML cloud spend.",
    )
    platforms = parser.add_subparsers(dest="platform", required=True)
    sf = platforms.add_parser("snowflake", help="Snowflake warehouse and storage scan")
    commands = sf.add_subparsers(dest="command", required=True)

    p = commands.add_parser("sql", help="write the export queries to hand to the client")
    p.add_argument("--out", type=Path, default=Path("snowflake_export_sql"))
    p.add_argument("--days", type=int, default=30, help="length of the export window")

    p = commands.add_parser("demo-data", help="generate a synthetic account export")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--scenario", choices=("before", "after"), default="before")
    p.add_argument(
        "--end", default=str(demo.DEFAULT_END.date()), help="window end date (UTC), YYYY-MM-DD"
    )
    p.add_argument("--seed", type=int, default=7)

    p = commands.add_parser("scan", help="analyse an export directory and write a report")
    p.add_argument("input", type=Path, help="directory with the exported CSV files")
    p.add_argument(
        "--credit-price", type=_positive, required=True, help="USD per credit (client contract)"
    )
    p.add_argument(
        "--storage-price",
        type=_positive,
        required=True,
        help="USD per TB-month of storage (client contract)",
    )
    p.add_argument("--target-auto-suspend", type=int, default=60, help="seconds")
    p.add_argument("--client", default="Snowflake account")
    p.add_argument("--fee-share", type=float, default=0.25)
    p.add_argument("--banner", help="note printed under the title, e.g. SYNTHETIC DATA")
    p.add_argument("--out", type=Path, help="markdown, or HTML when the path ends in .html")

    p = commands.add_parser("verify", help="compare exports before and after the changes")
    p.add_argument("--before", type=Path, required=True)
    p.add_argument("--after", type=Path, required=True)
    p.add_argument("--credit-price", type=_positive, required=True)
    p.add_argument("--client", default="Snowflake account")
    p.add_argument("--fee-share", type=float, default=0.25)
    p.add_argument("--out", type=Path, help="markdown, or HTML when the path ends in .html")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "sql":
            for path in write_extraction_queries(args.out, days=args.days):
                print(path)
        elif args.command == "demo-data":
            out = demo.generate(
                args.out,
                days=args.days,
                end=pd.Timestamp(args.end, tz="UTC"),
                scenario=args.scenario,
                seed=args.seed,
            )
            print(f"wrote synthetic export to {out}", file=sys.stderr)
        elif args.command == "scan":
            cfg = ScanConfig(
                credit_price=args.credit_price,
                storage_price_tb_month=args.storage_price,
                target_auto_suspend_s=args.target_auto_suspend,
            )
            result = run_scan(load_inputs(args.input), cfg)
            render = render_html if args.out and args.out.suffix == ".html" else render_markdown
            report = render(
                result, client=args.client, fee_share=args.fee_share, banner=args.banner
            )
            _emit(report, args.out)
        elif args.command == "verify":
            before = load_inputs(args.before, require_config=False)
            after = load_inputs(args.after, require_config=False)
            comparison = compare(before, after, args.credit_price)
            render = (
                render_verification_html
                if args.out and args.out.suffix == ".html"
                else render_verification
            )
            text = render(
                comparison,
                before,
                after,
                credit_price=args.credit_price,
                fee_share=args.fee_share,
                client=args.client,
            )
            _emit(text, args.out)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0
