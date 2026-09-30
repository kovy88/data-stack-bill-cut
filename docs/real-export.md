# First real export

No Snowflake login is configured on this machine (`SNOWFLAKE_*` is unset, and there is no `~/.snowflake` config visible to the workspace). The loader was not changed, because there is no real export to break it.

When an account is available:

```bash
uv run data-stack-bill-cut snowflake sql --out snowflake_export_sql --days 30
# run the seven files in Snowsight, save the CSVs into data/private/<client>/
uv run data-stack-bill-cut snowflake scan data/private/<client> \
    --credit-price <usd> --storage-price <usd> --client "<name>" \
    --out data/private/<client>/report.html
```

Do not quote that report until this command finishes on those files. If it raises `InputError`, fix the loader against that file only.
