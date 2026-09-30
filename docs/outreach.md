# Outreach templates

## Who to contact

- Companies using Snowflake: job posts mentioning Snowflake / dbt, especially ones hiring data
  engineers (a growing team usually means a growing bill).
- Roles: Head of Data, data platform / analytics engineering lead, CTO at companies < 200 people.
- Qualify early: rough monthly Snowflake bill, number of warehouses, who owns warehouse settings.
- **Do not contact:** insurance companies (Generali conflict), anyone connected to the employer.

## LinkedIn connection note (EN, < 300 chars)

> Hi {first_name}, I build read-only cost scans for Snowflake accounts: a written USD saving
> number per warehouse from your own query history. Free scan, fee only on savings verified on
> the invoice. Happy to share a sample report if useful.

## LinkedIn connection note (CZ)

> Dobrý den, {first_name}, dělám read-only analýzu nákladů na Snowflake: z vaší query history
> spočítám konkrétní úsporu v USD po jednotlivých warehousech. Scan je zdarma, platí se jen podíl
> z úspory ověřené na faktuře. Rád pošlu ukázkový report.

## Follow-up after connecting (EN)

> Thanks for connecting. In short: you run four metadata exports in Snowsight (15 minutes, no
> credentials shared, no table data). Two days later you get a report like this one
> {link to sample report} with the saving per finding and the exact ALTER statements.
> The method, with worked numbers, is in {link to article-auto-suspend}.
> If you apply the changes, my fee is 25 % of the annual saving that shows up on your bill after
> 60–90 days; if nothing shows up, you pay nothing.
> Would it be worth 15 minutes to look at your account?

## Follow-up (CZ)

> Díky za spojení. Stručně: ve Snowsight spustíte čtyři exporty metadat (15 minut, žádné přístupy
> nesdílíte, žádná data z tabulek). Do dvou dnů dostanete report jako tenhle {odkaz} s úsporou
> u každého nálezu a přesnými ALTER příkazy. Když změny nasadíte, beru si 25 % z roční úspory,
> která se po 60–90 dnech projeví na faktuře; když se neprojeví, neplatíte nic.
> Stálo by vám za to 15 minut se na váš účet podívat?

## Cold e-mail (EN)

Subject: Snowflake idle credits at {company}

> Hi {first_name},
>
> Most Snowflake bills have a share of credits billed while no query is running: auto-suspend
> tails, warehouses nobody uses, sizes chosen once and never revisited. How much depends entirely
> on the account, so I don't quote averages; I measure it.
>
> The scan uses four read-only exports from SNOWFLAKE.ACCOUNT_USAGE (no credentials, no table
> data) and returns a USD number per finding, priced at your contract rate. Sample on a synthetic
> account: {link}.
>
> Fee: 25 % of the verified annual saving, only after it shows on the invoice.
>
> Worth a look?
> Matěj

## Upwork / freelance proposal opener

> I'll give you a written USD saving number for your Snowflake account before you pay anything.
> Method: four read-only ACCOUNT_USAGE exports → per-warehouse billing model checked against
> your metered credits → report with the exact ALTER statements and their risks
> (sample: {link}). For this job I can do a fixed-price audit; for ongoing work I prefer a share
> of verified savings.
