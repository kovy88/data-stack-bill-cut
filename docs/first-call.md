# First call (90 minutes)

Use this when someone replies yes. Do not improvise the price or the scope.

## Before the call

- NDA in `docs/nda.md` is agreed before any file moves.
- Sample they already saw: https://cdn.jsdelivr.net/gh/kovy88/data-stack-bill-cut@main/docs/sample-report.html
- You need two numbers from their contract, not list price: USD per credit, and USD per TB-month of storage.

## On the call

1. Ask who owns warehouse settings, and the two prices above. Write them down.
2. They run the SQL from `uv run data-stack-bill-cut snowflake sql --out snowflake_export_sql --days 30` in Snowsight. Files 1–4 are enough for the warehouse and storage checks. Files 5–7 add cloud services and unused refresh. They can skip 5–7.
3. No login is shared. No table rows are read. Query text can be replaced with null.
4. They send the CSVs through the channel in the NDA. You put them in `data/private/<client>/`. That directory is gitignored.

## After the files arrive

```bash
uv run data-stack-bill-cut snowflake scan data/private/<client> \
    --credit-price <usd> --storage-price <usd> --client "<name>" \
    --out data/private/<client>/report.html
```

If this raises `InputError`, change `src/data_stack_bill_cut/snowflake/load.py` only enough to read that file. Do not quote a number until the command finishes.

Send back `report.html`. The fee sentence in it is the offer: 25% of the annual saving that shows on the invoice after 60–90 days, once, and nothing if it does not. Do not add an average from any other account.

## If there is no export yet

There is no Snowflake login on this machine. Do not change the loader, and do not quote a client figure, until a directory under `data/private/` contains their CSVs.
