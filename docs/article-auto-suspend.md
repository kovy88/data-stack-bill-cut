# Most of a Snowflake warehouse bill is the minute after the query finishes

Snowflake bills a running warehouse per second, with a 60-second minimum each time it wakes up.
It keeps billing after the last query until `AUTO_SUSPEND` fires. The default people leave in
place is 300 or 600 seconds. On a warehouse that wakes up every 15 minutes for a one-minute load,
that idle tail is most of the bill, and cutting it does not add a single extra resume.

The numbers below are from a **synthetic account** (`docs/sample-report.md`), priced at 3 USD per
credit. They show the shape of the waste. A real account gets its own measurement; nothing here
is an average you can quote.

## What the meter actually does

Take one warehouse, size Small (2 credits per hour), and a job every 15 minutes that runs for
60 seconds. `AUTO_SUSPEND = 300`.

Each cycle bills 60 seconds of work plus 300 seconds of idle, then the warehouse sleeps until
the next job. That is 360 billed seconds per job, 96 jobs a day:

- billed: 96 × 360 s × 2 credits/hour = **19.2 credits/day**
- of which the queries themselves are 96 × 60 s = **3.2 credits/day**

Set `AUTO_SUSPEND = 60` and the idle tail shrinks to the 60-second minimum. Same 96 resumes,
because the gap between jobs is still 14 minutes. The bill falls to **6.4 credits/day**.
At 3 USD per credit that is about **14,000 USD per year** on this one warehouse, and the resume
count does not move.

The same arithmetic on the synthetic account, checked against its hourly credit meter:

| Warehouse | Auto-suspend now | Idle share of the bill | Saving at 60 s | Resumes/day |
| --- | ---: | ---: | ---: | ---: |
| LOADING_WH | 300 s | 87 % | $14,016 | 96 → 96 |
| TRANSFORM_WH | 300 s | 33 % | $14,016 | 24 → 24 |
| DS_WH | 1,800 s | 88 % | $13,384 | 2 → 13 |
| BI_WH | 600 s | 96 % | $13,249 | 17 → 71 |
| LEGACY_REPORTING_WH | never | 100 % (zero queries) | $26,280 | suspend it |

Ready-to-apply total on that account: **$80,946 per year**, 41 % of a $197,569 warehouse-compute
bill. Two of the five changes do not increase resumes at all. The BI and data-science warehouses
do: each extra resume starts with a cold cache, so the report also prices 120, 300 and 600 seconds
and lets the owner pick.

## How to see it on your own account

You do not need to hand over a password. Four metadata exports from Snowsight (warehouse settings,
hourly credits, query start/end, table sizes) are enough. The model rebuilds the busy intervals
from query history, adds the auto-suspend tail, and checks the result against the credits
Snowflake actually billed. If the model overestimates the bill, the saving is scaled down to the
meter. It is never scaled up.

```sql
ALTER WAREHOUSE LOADING_WH SET AUTO_SUSPEND = 60;
```

One statement, reversible. After 60–90 days the same exports show whether credits per day, and
credits per 1,000 queries, actually fell.

---

# Většina účtu za Snowflake warehouse je minuta po skončení dotazu

Snowflake účtuje běžící warehouse po sekundách, s minimem 60 sekund při každém probuzení.
Po posledním dotazu účtuje dál, dokud nevyprší `AUTO_SUSPEND`. Často tam zůstane 300 nebo
600 sekund. U warehouse, který se každých 15 minut probudí na minutový load, je ten nečinný
ocas většina faktury a jeho zkrácení nepřidá ani jedno probuzení navíc.

Čísla níže jsou ze **syntetického účtu** (`docs/sample-report.md`) při ceně 3 USD za kredit.
Ukazují tvar plýtvání. Skutečný účet se měří zvlášť; tohle není průměr, který by šlo citovat.

## Co měřič opravdu dělá

Warehouse Small (2 kredity za hodinu), job každých 15 minut, běh 60 sekund, `AUTO_SUSPEND = 300`.

Každý cyklus: 60 sekund práce a 300 sekund nečinnosti, pak spánek do dalšího jobu. To je
360 účtovaných sekund na job, 96 jobů denně:

- účtováno: 96 × 360 s × 2 kredity/hod = **19,2 kreditu/den**
- z toho samotné dotazy: **3,2 kreditu/den**

`AUTO_SUSPEND = 60` zkrátí nečinný ocas na 60sekundové minimum. Pořád 96 probuzení, protože mezera
mezi joby je 14 minut. Účet klesne na **6,4 kreditu/den**. Při 3 USD za kredit je to zhruba
**14 000 USD ročně** na jednom warehouse a počet probuzení se nezmění.

Stejný výpočet na syntetickém účtu, ověřený proti hodinovému měřiči kreditů:

| Warehouse | Auto-suspend teď | Podíl nečinnosti | Úspora při 60 s | Probuzení/den |
| --- | ---: | ---: | ---: | ---: |
| LOADING_WH | 300 s | 87 % | 14 016 USD | 96 → 96 |
| TRANSFORM_WH | 300 s | 33 % | 14 016 USD | 24 → 24 |
| DS_WH | 1 800 s | 88 % | 13 384 USD | 2 → 13 |
| BI_WH | 600 s | 96 % | 13 249 USD | 17 → 71 |
| LEGACY_REPORTING_WH | nikdy | 100 % (nula dotazů) | 26 280 USD | uspat |

Připravené k nasazení: **80 946 USD ročně**, 41 % z účtu 197 569 USD za warehouse compute.
Dvě z pěti změn počet probuzení nezvednou. U BI a data-science warehouse ano: každé další
probuzení startuje se studenou cache, proto report naceňuje i 120, 300 a 600 sekund.

## Jak to změřit na vlastním účtu

Heslo předávat nemusíte. Stačí čtyři exporty metadat ze Snowsight (nastavení warehouse,
hodinové kredity, začátek a konec dotazů, velikosti tabulek). Model složí intervaly, kdy
warehouse pracoval, přičte ocas auto-suspend a výsledek srovná s kredity, které Snowflake
opravdu naúčtoval. Když model účet nadhodnotí, úspora se zmenší na měřenou částku. Nenavyšuje se.

```sql
ALTER WAREHOUSE LOADING_WH SET AUTO_SUSPEND = 60;
```

Jeden příkaz, vratný. Po 60–90 dnech stejné exporty ukážou, jestli kredity za den a kredity
na 1 000 dotazů opravdu klesly.
