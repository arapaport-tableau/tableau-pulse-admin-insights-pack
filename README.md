# Pulse Admin Insights Starter Pack

A set of prebuilt Tableau Pulse metrics that install on the standard **Admin Insights** data
sources every Tableau Cloud site already has. Point the tool at your site, run it, and you get
nine ready-made metrics on your own Tableau usage data. No data prep, no modeling, no wait.

The goal is speed to value. Pulse asks people to think in metrics, and most teams stall on the
blank page. Starting them on real data they already care about (how their own site is being used)
lets them feel what Pulse does the day they turn it on.

> **Most people should use the app, not the command line.** Download this tool, double-click the
> launcher, and follow three on-screen steps. No terminal, no commands, no config files. Jump to
> [Using the app](#using-the-app). The command line is only for people who prefer a terminal or are
> scripting it across many sites ([CLI.md](CLI.md)).

This is an unofficial community tool. It is not built or supported by Tableau or Salesforce.

## What you get

Nine trend metrics across three themes, all on event-log sources that keep real history, so every
metric trends and compares period over period from day one.

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

---

# How to run it

There are two ways. Most people should use the app.

- **The app (recommended).** A small window that opens in your browser. You type in four things,
  review a plan, and click a button. No commands to type. Steps are below.
- **The command line.** For people who prefer a terminal or are scripting it across many sites.
  See [CLI.md](CLI.md).

Both do exactly the same thing under the hood, so you can set up with one and undo with the other.

## Before you start (three quick things)

1. **Your Tableau site needs three settings turned on:** Admin Insights, Tableau Pulse, and the
   VizQL Data Service. If you're a **Site Administrator** you can turn these on under **Settings**.
   If not, send that list to whoever manages your Tableau site.
2. **A Personal Access Token (PAT).** This is a password-like key the app uses to sign in for you.
   In Tableau, click your profile picture (top right) → **My Account Settings** → scroll to
   **Personal Access Tokens** → type a name like `Pulse Pack`, click **Create Token**, and **copy
   the secret it shows you** (Tableau shows it only once). Keep the token *name* and the *secret*.
3. **Python 3.10 or newer**, a free program the app runs on. To check, open Terminal (Mac) or
   Command Prompt (Windows) and type `python3 --version`. If it prints a version 3.10 or higher,
   you're set. If not, install it from [python.org/downloads](https://www.python.org/downloads/)
   (on Windows, check **"Add Python to PATH"** during install).

## Using the app

1. **Download this tool.** On its GitHub page, click the green **Code** button → **Download ZIP**,
   then unzip it. You'll have a folder named `tableau-pulse-admin-insights-pack`.
2. **Start it.**
   - **Mac:** double-click **`Start Pulse Pack.command`** in that folder. The first time, macOS may
     say the file is from an unidentified developer. If so, right-click the file, choose **Open**,
     then click **Open** in the dialog. You only do this once.
   - **Windows:** double-click **`Start Pulse Pack.bat`**.

   The first launch takes a minute or two to set itself up. After that it's instant. A small
   window opens, and your browser opens to the app automatically.
3. **Follow the three on-screen steps:**
   - **Connect:** paste your Tableau web address and site name, and your token name and secret.
     Each field has a "Where do I find this?" helper if you're unsure. Click **Check connection**.
   - **Review:** the app shows you exactly what it *would* create. Nothing has been made yet.
     Choose whether to create a team group and whether to follow the metrics yourself.
   - **Create:** click the button and watch it work. When it's done you'll see a summary and a link
     straight to your Pulse page.

That's it. Give new metrics a couple of minutes to fill in with data.

### To remove everything

On the final screen, click **Remove what this app added**. It deletes only the metrics the app
created (and the group, if the app made it) and leaves everything else on your site untouched. It
shows you the exact list before removing anything.

### When you're finished

Close the browser tab, then close the small window the launcher opened (or press Ctrl+C in it).
Nothing keeps running in the background, and nothing is left on your computer except the tool
folder you downloaded.

---

## How it stays portable

Admin Insights is auto-provisioned on every Cloud site with a standardized schema, which is what
makes one pack work everywhere. The only per-site variable is each source's LUID, which the tool
looks up by name at run time. Field names are resolved through the VizQL Data Service (the same
field list the Pulse UI reads), so the pack maps friendly names to your site's internal field
names automatically. If a field cannot be resolved (for example on a non-English site), the tool
stops and tells you rather than creating something broken.

The pack targets the standard **`... (local)`** Admin Insights sources (the copies published into
your site's Admin Insights project). If a site name matches more than one datasource, the tool
prefers the one in the **Admin Insights** project and tells you in the plan so you can confirm it
picked the right one.

## Safety

- Only ever creates net-new Pulse definitions (and, if you ask, a group and subscriptions). It
  never touches your data, existing content, or site settings.
- The preview (the app's Review screen, or `--dry-run` on the command line) writes nothing.
- It never edits a definition it didn't create. Descriptions and the week-to-date period are set
  only on definitions this run created; anything pre-existing that it adopts is left as-is.
- Idempotent: a metric that already exists with the same specification is adopted rather than
  duplicated (matched by name and spec, so a rename of one of ours still matches). Re-running is
  safe.
- Your sign-in details never leave your computer. The app runs on `127.0.0.1` (your machine only),
  holds the token secret in memory just long enough to sign in, and never writes it to disk. No
  credentials are stored; you enter them fresh each run.
- State is tracked per site in `manifest.<site_id>.json` (gitignored), so running against several
  sites doesn't cross the streams. Removal deletes only the definitions this tool created,
  unfollows any it merely adopted, and deletes the group only if the tool created it. If the state
  file is gone, it falls back to discovering the pack from the follow group and asks you to confirm
  before deleting; in that mode it warns that it can't tell created from adopted.
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
  definition the tool sets the default metric to week-to-date (`GRANULARITY_BY_WEEK` + current
  partial period), which suits the daily-refresh usage data. Change `default_granularity` on any
  metric in `metrics.manifest.json` to pick a different period.
- **Group follow is all-or-nothing and forward-looking.** When you create a group, every current
  *and future* member follows all nine metrics. Use a group you're comfortable auto-subscribing.
- **Data freshness follows Admin Insights**, which refreshes daily and keeps roughly a 90-day
  rolling window. New metrics take a couple of minutes to index before they populate, so a
  just-created metric can look empty at first.
- A few filter values (error-code categories, job result and job type strings) are set to the
  standard English Admin Insights values. The preview counts the rows each filter matches and flags
  any that come back empty, so you can confirm they line up with your own data before you commit.

## For developers

`engine.py` holds all the logic. `deploy.py` is the command-line face and `app.py` is the local
web face; both call the same engine, so behavior and safety are identical. See [CLI.md](CLI.md) for
the full command reference.
