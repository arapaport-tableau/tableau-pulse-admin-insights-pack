#!/usr/bin/env python3
"""
deploy.py — Pulse Admin Insights Starter Pack installer (command line).

Creates a set of prebuilt Tableau Pulse metric definitions on the standard Admin Insights
data sources that ship with every Tableau Cloud site. No data prep. The metrics are authored
once in metrics.manifest.json using human-readable field captions; at deploy time the shared
engine resolves each caption to Pulse's internal fieldName via the VizQL Data Service (the same
field list the Pulse UI reads), so the pack is portable to any site regardless of its LUIDs.

All the logic lives in engine.py; this file is just the command-line face of it. There is a
second face, app.py, a local web GUI for non-technical users. Both call the same engine, so they
behave identically (same defaults, same safety guarantees, same per-site state files).

Safe by design (enforced in the engine):
  - Only ever CREATES net-new Pulse definitions (and, optionally, a group + subscriptions).
    It never edits a definition it did not create, and never touches data or site settings.
  - Idempotent and collision-aware: metrics are matched by NAME and by full SPECIFICATION
    (Pulse dedups on spec, not name), so re-runs adopt what already exists instead of failing.
  - --dry-run makes no writes at all and validates filter values against live data.
  - --uninstall removes exactly what this tool created, and can rediscover its own metrics
    from the group that follows them when the local state file is gone.

Usage:
  ./.venv/bin/python deploy.py --dry-run          # show the full plan + validation, write nothing
  ./.venv/bin/python deploy.py                     # create the definitions (inert; nothing followed)
  ./.venv/bin/python deploy.py --group "Admin Insights Metrics"   # + create/reuse group, follow all
  ./.venv/bin/python deploy.py --follow            # + subscribe the running user to every metric
  ./.venv/bin/python deploy.py --uninstall --dry-run   # preview a cleanup
  ./.venv/bin/python deploy.py --uninstall         # remove exactly what a prior run created

Connection details come from (in order): env vars, config.json (gitignored), then prompts.
The PAT secret is read via getpass, never echoed and never written to disk.

Run with the project venv (system python3 is 3.9 and incompatible with TSC 0.41):
    ./.venv/bin/python deploy.py [flags]
"""

import argparse
import getpass
import json
import os
import sys

import engine

CONFIG_PATH = os.path.join(engine.HERE, "config.json")   # optional creds (gitignored)


# ── Connection ──────────────────────────────────────────────────────────────────
def load_connection():
    cfg = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)

    def pick(env, key, prompt, default=None, secret=False):
        val = os.environ.get(env) or cfg.get(key)
        if val:
            return str(val).strip()
        if secret:
            # getpass never echoes (so the secret can't be seen or screen-shared).
            # Loop until something is entered and confirm receipt, so it's clear the
            # keystrokes registered even though nothing shows while typing.
            while True:
                entered = getpass.getpass(prompt).strip()
                if entered:
                    print(f"  Got it (received {len(entered)} characters; input stays hidden).")
                    return entered
                print("  Nothing entered. Paste the secret and press Enter.")
        entered = input(prompt).strip()
        return entered or (default or "")

    server_url = pick("SERVER_URL", "server_url",
                      "Server URL (e.g. https://10ax.online.tableau.com): ").rstrip("/")
    site_name = pick("SITE_NAME", "site_name", "Site content URL: ")
    pat_name = pick("PAT_NAME", "pat_name", "PAT name: ")
    pat_secret = pick("PAT_SECRET", "pat_secret",
                      "PAT secret (typing stays hidden, then press Enter): ", secret=True)
    return server_url, site_name, pat_name, pat_secret


# ── CLI: deploy ───────────────────────────────────────────────────────────────
def cli_deploy(server, server_url, token, ir, args):
    print("\n[1/4] Resolving sources and [2/4] reading field maps...")
    try:
        plan = engine.build_plan(server, server_url, token, ir, log=lambda m: print("      " + m))
    except engine.EngineError as e:
        sys.exit(f"\n  {e.message}\n  {e.hint}")

    if args.on_conflict == "skip":
        conflicts = [it for it in plan["items"] if it["action"] == "conflict"]
        if conflicts:
            print(f"\n  Note: {len(conflicts)} name(s) already exist with a different spec and will "
                  "be SKIPPED. Re-run with --on-conflict suffix to create those under a distinct name.")

    if args.dry_run:
        grans = ", ".join(plan["granularities"])
        print(f"\n  Default metric period would be set to: {grans} + {plan['default_range']}.")
        results = engine.validate_filters(server_url, token, plan, log=lambda m: print("  " + m))
        if not results:
            print("  (no confirm:true filters to validate)")
        print("\n  --dry-run: no writes made. Plan above is what a real run would do.")
        return

    print("\n[4/4] Creating definitions...")
    try:
        summary = engine.execute_deploy(
            server, server_url, token, ir, plan,
            group=args.group, follow=args.follow, on_conflict=args.on_conflict,
            site_name=args.site_name, log=lambda m: print("      " + m))
    except engine.EngineError as e:
        sys.exit(f"\n  {e.message}\n  {e.hint}")

    print(f"\n  Wrote {summary['state_file']}. Created {summary['created']} new, "
          f"{summary['adopted']} adopted, {summary['skipped']} skipped (name conflict).")
    print("  Allow 2-3 minutes for Pulse to index new metrics before they populate.")


# ── CLI: uninstall ────────────────────────────────────────────────────────────
def cli_uninstall(server, server_url, token, args):
    try:
        uplan = engine.uninstall_plan(server, server_url, token, group=args.group,
                                      force=args.force, log=lambda m: print("      " + m))
    except engine.EngineError as e:
        sys.exit(f"\n  {e.message}\n  {e.hint}")

    if uplan["mode"] == "state":
        print("\n[uninstall] Plan (precise, from state file):")
        for r in uplan["to_delete"]:
            print(f"      delete definition  {r['name']}")
        for r in uplan["to_unfollow"]:
            print(f"      unfollow (adopted) {r['name']}")
        for r in uplan["to_keep"]:
            print(f"      keep (pre-existing) {r['name']}")
        if uplan["group"]:
            verb = "delete" if uplan["group"]["action"] == "delete" else "keep (pre-existing)"
            print(f"      {verb} group '{uplan['group']['name']}'")
    else:
        print("\n[uninstall] No state file for this site. Discovering via the follow group...")
        print("  WARNING: " + uplan["warning"])
        for r in uplan["to_delete"]:
            print(f"      would delete definition {r['definition_id']}")
        if uplan["group"]:
            print(f"      would delete group '{uplan['group']['name']}'")

    if args.dry_run:
        print("\n  --dry-run: no deletions made.")
        return
    if uplan["needs_confirmation"] and not args.yes:
        ans = input("\n  Type 'delete' to remove the above, anything else to abort: ").strip()
        if ans != "delete":
            sys.exit("  Aborted. Nothing deleted.")

    summary = engine.execute_uninstall(server, server_url, token, uplan,
                                       log=lambda m: print("      " + m))
    print(f"\n  Removed {summary['removed']} definition(s). Deleting a definition also removes its "
          "metrics and subscriptions.")


# ── Main ────────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="Deploy the Pulse Admin Insights Starter Pack.")
    ap.add_argument("--dry-run", action="store_true", help="show the plan (and validate filters), write nothing")
    ap.add_argument("--follow", action="store_true", help="subscribe the running user to every metric")
    ap.add_argument("--group", metavar="NAME", nargs="?", const=engine.DEFAULT_GROUP_NAME,
                    help=f"create-or-reuse this group and subscribe it to every metric "
                         f"(default name: '{engine.DEFAULT_GROUP_NAME}')")
    ap.add_argument("--on-conflict", choices=["skip", "suffix"], default="skip",
                    help="when a name exists with a DIFFERENT spec: skip it (default) or create "
                         "ours under a suffixed name")
    ap.add_argument("--uninstall", action="store_true", help="delete only what a prior run created")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt on discovery uninstall")
    ap.add_argument("--force", action="store_true", help="override the site-match guard on uninstall")
    args = ap.parse_args()

    ir = engine.load_ir()
    server_url, site_name, pat_name, pat_secret = load_connection()
    args.site_name = site_name

    print(f"\nSigning in to {server_url} / {site_name} ...")
    try:
        server = engine.sign_in(server_url, site_name, pat_name, pat_secret)
    except engine.EngineError as e:
        sys.exit(f"  {e.message}\n  {e.hint}")
    token = server.auth_token
    print(f"  Connected (REST {server.version}).")

    try:
        if args.uninstall:
            cli_uninstall(server, server_url, token, args)
        else:
            cli_deploy(server, server_url, token, ir, args)
    finally:
        server.auth.sign_out()


if __name__ == "__main__":
    main()
