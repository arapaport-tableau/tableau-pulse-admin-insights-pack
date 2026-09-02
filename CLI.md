# Command-line guide

The app (see the [README](README.md)) is the easy path and does everything this page describes
through a friendly window. This page is for people who prefer a terminal, want to script it, or
are running it against many sites.

The app and the command line share the same engine (`engine.py`), so they behave identically:
same defaults, same safety guarantees, same per-site state files. Anything you do with one, you
can undo with the other.

New words you'll see, in plain English:
- **Terminal** (or **Command Prompt** on Windows): a plain text window where you type commands.
- **Personal Access Token (PAT)**: a password-like key that lets the tool sign in to your site on
  your behalf. You create it once and can delete it any time.
- **Server address** and **site name**: two pieces of your site's web address (explained in Step 3).

## Step 1: Make sure your site is ready

This tool needs three things turned on for your Tableau Cloud site. If you are a **Site
Administrator**, you can check and turn these on yourself under **Settings**. If you are not an
admin, send this list to whoever manages your Tableau site and ask them to confirm all three:

1. **Admin Insights** is enabled.
2. **Tableau Pulse** is enabled.
3. **VizQL Data Service** is enabled.

## Step 2: Create your Personal Access Token (your sign-in key)

1. Sign in to your Tableau Cloud site in a web browser.
2. Click your profile picture in the top right, then choose **My Account Settings**.
3. Scroll down to the section called **Personal Access Tokens**.
4. Type a name for your token (for example, `Pulse Pack`) and click **Create Token**.
5. A box appears with a long secret string. **Copy it now and paste it somewhere safe.** Tableau
   only shows it once. You will paste it into the tool in Step 7.

Keep both the **token name** you typed and the **secret** you copied. You need both.

## Step 3: Find your server address and site name

Look at the web address (URL) in your browser while you are signed in to Tableau:

```
https://10ax.online.tableau.com/#/site/acmecorp/home
```

From that address you need two pieces:
- **Server address**: the first part, ending in `.online.tableau.com`. In the example that is
  `https://10ax.online.tableau.com`. (Your part before `.online` may differ, such as `10az` or
  `prod-uswest-c`. That is normal.)
- **Site name**: the word right after `/site/`. In the example that is `acmecorp`. This is called
  the "content URL" in some Tableau screens.

## Step 4: Install Python

The tool is written in Python. You need Python version 3.10 or newer.

- Check first. Open your Terminal (Mac: press Cmd+Space, type "Terminal", press Enter. Windows:
  open the Start menu, type "Command Prompt", press Enter) and type this, then press Enter:

  ```bash
  python3 --version
  ```

  If it prints something like `Python 3.11.5`, you are set. Skip to Step 5.
- If it says the command is not found, or shows a version below 3.10, download and install Python
  from [python.org/downloads](https://www.python.org/downloads/). On Windows, during install,
  check the box that says **"Add Python to PATH"**.

## Step 5: Download this tool

**The simple way (no extra software):** On the tool's GitHub page, click the green **Code** button,
then **Download ZIP**, and unzip it. **If you have Git:**

```bash
git clone https://github.com/arapaport-tableau/tableau-pulse-admin-insights-pack.git
```

## Step 6: Open the folder and set it up

1. In your Terminal, move into the folder you just downloaded. Type `cd ` (with a space after it),
   then drag the folder from your file browser onto the Terminal window and press Enter.
2. Run these two commands, one at a time:

   ```bash
   python3 -m venv .venv
   ./.venv/bin/pip install -r requirements.txt
   ```

   The first creates a private workspace so this tool does not affect anything else on your
   computer. The second downloads the small helpers it needs. This is a one-time setup.

   > **On Windows**, the second command is `.venv\Scripts\pip install -r requirements.txt`, and
   > everywhere below where you see `./.venv/bin/python`, use `.venv\Scripts\python` instead.

## Step 7: Do a practice run (nothing gets created)

```bash
./.venv/bin/python deploy.py --dry-run
```

It asks four things, one at a time:
- **Server URL**: paste the server address from Step 3.
- **Site content URL**: type the site name from Step 3.
- **PAT name**: type the token name from Step 2.
- **PAT secret**: paste the secret from Step 2, then press Enter. Nothing appears on screen as you
  paste (on purpose, so no one can read it over your shoulder). After you press Enter, the tool
  prints "Got it" to confirm it received your input.

Then it prints a plan: the nine metrics, and for each whether it would be **created** (new) or
**adopted** (already exists and matches). Errors here? See [If something goes wrong](#if-something-goes-wrong).

## Step 8: Create the metrics for real

```bash
./.venv/bin/python deploy.py
```

Same four questions, then it creates the nine metrics. Re-running is safe: it skips anything that
already exists.

## Step 9 (recommended): Create a group so your team follows the metrics

```bash
./.venv/bin/python deploy.py --group
```

This creates a group called "Admin Insights Metrics" and makes it follow all nine metrics. Anyone
you add to that group later automatically follows them too. The tool does **not** add people to
the group; you stay in control of membership (Tableau → **Users and Groups**). To also follow the
metrics yourself right away, add `--follow`:

```bash
./.venv/bin/python deploy.py --group --follow
```

## Step 10: See your metrics in Pulse

Open Tableau Cloud and go to **Pulse** in the left menu. Give it a couple of minutes after
creating; a brand-new metric can look empty until Tableau fills in the data.

## Step 11: How to remove everything (the undo button)

```bash
./.venv/bin/python deploy.py --uninstall --dry-run   # shows what would be removed
./.venv/bin/python deploy.py --uninstall             # actually removes it
```

It deletes only the metrics this tool made, and the group only if the tool created it. Anything
that already existed is left untouched.

## Command reference

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

To avoid retyping connection details every run, copy `config.example.json` to `config.json` (which
is ignored by Git and never uploaded) and fill in `server_url`, `site_name`, and `pat_name`. The
secret is always typed at the hidden prompt and is never saved to a file.

## If something goes wrong

- **"command not found: python3"** — Python is not installed or not on your PATH. Redo Step 4. On
  Windows, reinstall and check "Add Python to PATH."
- **Sign-in failed** — Check three things: the **PAT name** matches exactly what you typed in
  Tableau (capitals and spaces count), the **site name** is the word after `/site/` (not the whole
  address), and the **server address** is your real pod (the part before `.online.tableau.com`).
  Tokens also expire after a period of no use; if in doubt, create a fresh one (Step 2).
- **Admin Insights or Pulse is not available** — Those settings are off. Go back to Step 1 and
  confirm with your site admin.
- **VizQL Data Service is disabled** — Turn it on under Settings (Step 1), then try again.
- **A metric shows "conflict" in the plan** — A metric with that same name already exists but is
  set up differently. The tool leaves it alone by default. Use `--on-conflict suffix` to create
  ours alongside it.
- **A metric looks empty right after creating it** — Give it a few minutes. Admin Insights data
  refreshes daily and new metrics take a short time to index.
