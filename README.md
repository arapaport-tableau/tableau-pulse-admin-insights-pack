# Pulse Admin Insights Starter Pack

A set of prebuilt Tableau Pulse metrics that install on the standard **Admin Insights** data
sources every Tableau Cloud site already has. Point the tool at your site, run it, and you get
nine ready-made metrics on your own Tableau usage data. No data prep, no modeling, no wait.

The goal is speed to value. Pulse asks people to think in metrics, and most teams stall on the
blank page. Starting them on real data they already care about (how their own site is being used)
lets them feel what Pulse does the day they turn it on.

This is an unofficial community tool. It is not built or supported by Tableau or Salesforce.

## What you get

Nine trend metrics across three themes, all on event-log sources that keep real history, so
every metric trends and compares period over period from day one.

**Adoption (TS Events)**
- Active Users
- Site Logins
- Content Views
- Unique Content Accessed
- New Content Published

**Performance (Viz Load Times)**
- Average View Load Time
- Load Errors

**Reliability (Job Performance)**
- Extract Refresh Failures
- Average Job Duration

See [METRICS.md](METRICS.md) for what each one tells you and why it matters.

## How it stays portable

Admin Insights is auto-provisioned on every Cloud site with a standardized schema, which is what
makes one pack work everywhere. The only per-site variable is each source's LUID, which the tool
looks up by name at run time. Field names are resolved through the VizQL Data Service (the same
field list the Pulse UI reads), so the pack maps friendly names to your site's internal field
names automatically. If a field cannot be resolved (for example on a non-English site), the tool
stops and tells you rather than creating something broken.

The pack targets the standard **`... (local)`** Admin Insights sources (the copies published into
your site's Admin Insights project). If a site name matches more than one datasource, the tool
prefers the one in the **Admin Insights** project and warns you in the plan so you can confirm it
picked the right one.

## Prerequisites

- Tableau Cloud site with **Admin Insights enabled** (Settings, or ask your site admin).
- **Pulse enabled** on the site.
- A **Personal Access Token**. The running user needs permission to create Pulse metric
  definitions (typically Site Administrator, or a Creator/Explorer with metric creation allowed).
- **VizQL Data Service enabled** on the site (Settings). The tool uses it to resolve field names
  and to validate filter values; it exits with a clear message if it's off.
- **Tableau Cloud 2024.2 (REST API 3.24) or newer.** The Pulse endpoints this tool calls don't
  exist on older releases; the tool checks at startup and stops with a version hint if they're
  missing.
- Python 3.10+.

## Setup

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

Connection details can come from a prompt (default), environment variables, or a `config.json`.
The PAT secret is always entered at a hidden prompt and is never written to disk. To avoid
re-typing the non-secret values, copy `config.example.json` to `config.json` (gitignored) and
fill in `server_url`, `site_name`, and `pat_name`.

## Usage

Always look before you write:

```bash
./.venv/bin/python deploy.py --dry-run
```

This signs in, resolves the Admin Insights sources, resolves every field, checks each metric
against what already exists (by name *and* full specification), validates the filter values against
your live data, and prints the full plan. It makes no changes.

Create the definitions (idempotent; safe to re-run):

```bash
./.venv/bin/python deploy.py
```

Recommended: create the definitions and have a group follow every one. Onboarding a teammate then
becomes "add them to the group," and the group is also what marks these metrics as belonging to the
pack. The tool does **not** add any users to the group; membership stays under your control.

```bash
./.venv/bin/python deploy.py --group
```

`--group` with no value uses "Admin Insights Metrics"; pass a name to use your own
(`--group "My Team"`). Add `--follow` to also subscribe yourself so you see a live feed immediately:

```bash
./.venv/bin/python deploy.py --group --follow
```

If a definition with the same **name but a different specification** already exists, the tool
leaves it untouched and skips ours by default (it never edits a definition it didn't create). To
create ours alongside it under a suffixed name instead:

```bash
./.venv/bin/python deploy.py --on-conflict suffix
```

Remove exactly what a prior run created:

```bash
./.venv/bin/python deploy.py --uninstall --dry-run   # preview first
./.venv/bin/python deploy.py --uninstall
```

## Safety

- Only ever creates net-new Pulse definitions (and, if you ask, a group and subscriptions). It
  never touches your data, existing content, or site settings.
- `--dry-run` writes nothing.
- It never edits a definition it didn't create. Descriptions and the week-to-date period are set
  only on definitions this run created; anything pre-existing that it adopts is left as-is.
- Idempotent: a metric that already exists with the same specification is adopted rather than
  duplicated (matched by name and spec, so a rename of one of ours still matches). Re-running is
  safe.
- State is tracked per site in `manifest.<site_id>.json` (gitignored), so running against several
  sites doesn't cross the streams. `--uninstall` refuses to run unless the state file matches the
  site you're signed in to (override with `--force`).
- `--uninstall` deletes only the definitions this tool created, unfollows any it merely adopted,
  and deletes the group only if the tool created it. Pre-existing objects are left alone. If the
  state file is gone, it falls back to discovering the pack from the follow group and asks you to
  confirm before deleting (`--yes` to skip the prompt); in that mode it warns that it can't tell
  created from adopted.
- Secrets never touch the repo. `config.json`, `manifest.json`, and `manifest.*.json` are
  gitignored.

## Notes and limits (v1)

- **English field names only.** Non-English or customized Admin Insights schemas may not resolve;
  the tool fails loudly rather than guessing.
- **Basic specifications only.** Threshold and ratio metrics (slow-load counts, success rates,
  inactive-user counts) need calculated expressions and are held for a later version.
- **Three sources, three conversations.** Pulse relates metrics that share a data source, so the
  nine metrics form three thematic clusters (Adoption, Performance, Reliability) rather than one.
  Adoption is the richest because all five of its metrics share TS Events.
- **Metrics land week-to-date.** Pulse creates every metric month-to-date; after creating each
  definition the tool sets the followed (default) metric to week-to-date (`GRANULARITY_BY_WEEK`
  + current partial period), which suits the daily-refresh usage data. Change `default_granularity`
  on any metric in `metrics.manifest.json` to pick a different period.
- **Group follow is all-or-nothing and forward-looking.** When you use `--group`, every current
  *and future* member of that group follows all nine metrics. Use a group you're comfortable
  auto-subscribing.
- **Data freshness follows Admin Insights**, which refreshes daily and keeps roughly a 90-day
  rolling window. New metrics take a couple of minutes to index before they populate, so a
  just-created metric can look empty at first.
- A few filter values (error-code categories, job result and job type strings) are set to the
  standard English Admin Insights values. `--dry-run` counts the rows each filter matches and flags
  any that come back empty, so you can confirm they line up with your own data before you commit.
