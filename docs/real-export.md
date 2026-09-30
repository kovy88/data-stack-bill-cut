# First real export

Checked 30 Sep 2026: `data/private/` does not exist, so no client export has arrived. The loader was not changed.

No Snowflake login is configured on this machine. The call steps are in `docs/first-call.md`.

When an account is available:

```bash
uv run data-stack-bill-cut snowflake sql --out snowflake_export_sql --days 30
# run the seven files in Snowsight, save the CSVs into data/private/<client>/
uv run data-stack-bill-cut snowflake scan data/private/<client> \
    --credit-price <usd> --storage-price <usd> --client "<name>" \
    --out data/private/<client>/report.html
```

Do not quote that report until this command finishes on those files. If it raises `InputError`, fix the loader against that file only.
