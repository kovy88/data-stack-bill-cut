from importlib.resources import files
from pathlib import Path


def extraction_queries(days: int = 30) -> dict[str, str]:
    if days < 1:
        raise ValueError("days must be >= 1")
    sql_dir = files("data_stack_bill_cut.snowflake") / "sql"
    return {
        entry.name: entry.read_text(encoding="utf-8").replace("{{DAYS}}", str(days))
        for entry in sorted(sql_dir.iterdir(), key=lambda e: e.name)
        if entry.name.endswith(".sql")
    }


def write_extraction_queries(out_dir: Path, days: int = 30) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, sql in extraction_queries(days).items():
        path = out_dir / name
        path.write_text(sql, encoding="utf-8")
        written.append(path)
    return written
