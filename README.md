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

---

# Start here: step-by-step guide

You do not need to be a developer to run this. If you can copy and paste a few commands, you can
do this. The whole thing takes about 15 minutes. Follow the steps in order.

New words you will see, in plain English:
- **Terminal** (or **Command Prompt** on Windows): a plain text window where you type commands.
- **Personal Access Token (PAT)**: a password-like key that lets the tool sign in to your site
  on your behalf. You create it once and can delete it any time.
- **Server address** and **site name**: two pieces of your site's web address (explained in Step 3).

## Step 1: Make sure your site is ready

This tool needs three things turned on for your Tableau Cloud site. If you are a **Site
Administrator**, you can check and turn these on yourself under **Settings**. If you are not an
admin, send this list to whoever manages your Tableau site and ask them to confirm all three:

1. **Admin Insights** is enabled.
2. **Tableau Pulse** is enabled.
3. **VizQL Data Service** is enabled.

Your site also needs to be on **Tableau Cloud version 2024.2 or newer**. Most sites already are.
If it is older, the tool will tell you clearly and stop.

## Step 2: Create your Personal Access Token (your sign-in key)

1. Sign in to your Tableau Cloud site in a web browser.
2. Click your profile picture in the top right, then choose **My Account Settings**.
3. Scroll down to the section called **Personal Access Tokens**.
4. Type a name for your token (for example, `Pulse Pack`) and click **Create Token**.
5. A box appears with a long secret string. **Copy it now and paste it somewhere safe** (like a
   sticky note in a password manager). Tableau only shows it once. You will paste it into the
   tool in Step 7.

Keep both the **token name** you typed and the **secret** you copied. You need both.

## Step 3: Find your server address and site name

Look at the web address (URL) in your browser while you are signed in to Tableau. It looks
something like this:

```
https://10ax.online.tableau.com/#/site/acmecorp/home
```

From that address you need two pieces:
- **Server address**: the first part, ending in `.online.tableau.com`. In the example that is
  `https://10ax.online.tableau.com`. (Your part before `.online` may differ, such as `10az` or
  `prod-uswest-c`. That is normal.)
- **Site name**: the word right after `/site/`. In the example that is `acmecorp`. This is called
  the "content URL" in some Tableau screens.

Write both down. You will type them into the tool in Step 7.

## Step 4: Install Python (a free program the tool runs on)

The tool is written in Python. You need Python version 3.10 or newer.

- First, check if you already have it. Open your Terminal (Mac: press Cmd+Space, type
  "Terminal", press Enter. Windows: open the Start menu, type "Command Prompt", press Enter) and
  type this, then press Enter:

  ```bash
  python3 --version
  ```

  If it prints something like `Python 3.11.5`, you are set. Skip to Step 5.
- If it says the command is not found, or shows a version below 3.10, download and install Python
  from [python.org/downloads](https://www.python.org/downloads/). On Windows, during install,
  check the box that says **"Add Python to PATH"**.

## Step 5: Download this tool

Two easy ways. Pick one.

**The simple way (no extra software):**
1. Go to the tool's page on GitHub.
2. Click the green **Code** button, then **Download ZIP**.
3. Unzip the downloaded file. You now have a folder called
   `tableau-pulse-admin-insights-pack`.

**If you have Git installed:**
```bash
git clone https://github.com/arapaport-tableau/tableau-pulse-admin-insights-pack.git
```

## Step 6: Open the folder and set it up

1. In your Terminal, move into the folder you just downloaded. Type `cd ` (with a space after
   it), then drag the folder from your file browser onto the Terminal window and press Enter.
   That fills in the folder location for you.
2. Run these two commands, one at a time (press Enter after each, and wait for the first to
   finish before running the second):

   ```bash
   python3 -m venv .venv
   ./.venv/bin/pip install -r requirements.txt
   ```

   The first line creates a private workspace so this tool does not affect anything else on your
   computer. The second downloads the two small helpers the tool needs. This is a one-time setup.

   > **On Windows**, the second command is slightly different:
   > ```
   > .venv\Scripts\pip install -r requirements.txt
   > ```
   > and everywhere below where you see `./.venv/bin/python`, use `.venv\Scripts\python` instead.

## Step 7: Do a practice run (nothing gets created)

Always look before you leap. This command signs in, checks everything, and shows you exactly what
it *would* do. It does not create anything.

```bash
./.venv/bin/python deploy.py --dry-run
```

It will ask you four things, one at a time:
- **Server URL**: paste the server address from Step 3.
- **Site content URL**: type the site name from Step 3.
- **PAT name**: type the token name from Step 2.
- **PAT secret**: paste the secret from Step 2. (It stays hidden as you paste. That is normal.
  Just press Enter.)

Then it prints a plan: the nine metrics, and for each one whether it would be **created** (new) or
**adopted** (already exists and matches). If you see errors here, jump to
[If something goes wrong](#if-something-goes-wrong) below.

## Step 8: Create the metrics for real

When the practice run looks good, run the same command without `--dry-run`:

```bash
./.venv/bin/python deploy.py
```

It asks the same four questions, then creates the nine metrics on your site. Running it again
later is safe: it skips anything that already exists.

## Step 9 (recommended): Create a group so your team follows the metrics

This creates a group called "Admin Insights Metrics" and makes it follow all nine metrics.
Anyone you add to that group later automatically follows them too. Onboarding a teammate becomes
as simple as adding them to the group.

```bash
./.venv/bin/python deploy.py --group
```

The tool does **not** add any people to the group. You stay in control of who is in it (add
members in Tableau under **Users and Groups**). If you also want to follow the metrics yourself
right away, add `--follow`:

```bash
./.venv/bin/python deploy.py --group --follow
```

## Step 10: See your metrics in Pulse

Open Tableau Cloud in your browser and go to **Pulse** in the left menu. Your new metrics appear
there. Give it a couple of minutes after creating them; Tableau needs a moment to fill in the
data, so a brand-new metric can look empty at first.

## Step 11: How to remove everything (the undo button)

Changed your mind? This removes exactly what the tool created and nothing else. Always preview
first with `--dry-run`:

```bash
./.venv/bin/python deploy.py --uninstall --dry-run   # shows what would be removed
./.venv/bin/python deploy.py --uninstall             # actually removes it
```

It deletes only the metrics this tool made, and the group only if the tool created it. Anything
that already existed on your site is left untouched.

---

## Command reference

For when you know your way around and just want the list.

| Command | What it does |
|---|---|
| `deploy.py --dry-run` | Show the plan and validate everything. Writes nothing. |
| `deploy.py` | Create the nine definitions. Safe to re-run. |
| `deploy.py --group [NAME]` | Create-or-reuse a group and have it follow every metric. Default name "Admin Insights Metrics". |
| `deploy.py --follow` | Also subscribe you (the running user) to every metric. |
| `deploy.py --on-conflict suffix` | If a name exists with a *different* setup, create ours under a suffixed name instead of skipping. |
| `deploy.py --uninstall [--dry-run]` | Remove only what a prior run created. Preview with `--dry-run`. |
| `deploy.py --uninstall --yes` | Skip the confirmation prompt when uninstalling without a saved record. |
| `deploy.py --uninstall --force` | Override the safety check that uninstall matches the site you created on. |

To avoid retyping the connection details every run, copy `config.example.json` to `config.json`
(which is ignored by Git and never uploaded) and fill in `server_url`, `site_name`, and
`pat_name`. The secret is always typed at the hidden prompt and is never saved to a file.

## If something goes wrong

- **"command not found: python3"** — Python is not installed or not on your PATH. Redo Step 4. On
  Windows, reinstall and check "Add Python to PATH."
- **It says sign-in failed** — Double-check three things: the **PAT name** matches exactly what
  you typed in Tableau (capitals and spaces count), the **site name** is the word after `/site/`
  (not the whole address), and the **server address** is your real pod (the part before
  `.online.tableau.com`). Tokens also expire after a period of no use; if in doubt, create a fresh
  one (Step 2).
- **It says Admin Insights or Pulse is not available** — Those settings are off, or you are not on
  a recent enough version. Go back to Step 1 and confirm with your site admin.
- **It says VizQL Data Service is disabled** — Turn it on under Settings (Step 1), then try again.
- **A metric shows "conflict" in the plan** — A metric with that same name already exists on your
  site but is set up differently. The tool leaves it alone by default. Use `--on-conflict suffix`
  if you want ours created alongside it.
- **A metric looks empty right after creating it** — Give it a few minutes. Admin Insights data
  refreshes daily and new metrics take a short time to index.

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
prefers the one in the **Admin Insights** project and warns you in the plan so you can confirm it
picked the right one.

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
  definition the tool sets the default metric to week-to-date (`GRANULARITY_BY_WEEK` + current
  partial period), which suits the daily-refresh usage data. Change `default_granularity` on any
  metric in `metrics.manifest.json` to pick a different period.
- **Group follow is all-or-nothing and forward-looking.** When you use `--group`, every current
  *and future* member of that group follows all nine metrics. Use a group you're comfortable
  auto-subscribing.
- **Data freshness follows Admin Insights**, which refreshes daily and keeps roughly a 90-day
  rolling window. New metrics take a couple of minutes to index before they populate, so a
  just-created metric can look empty at first.
- A few filter values (error-code categories, job result and job type strings) are set to the
  standard English Admin Insights values. `--dry-run` counts the rows each filter matches and flags
  any that come back empty, so you can confirm they line up with your own data before you commit.
